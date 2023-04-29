#!/usr/bin/env python3
import os
import time
import signal
import requests
import threading
import subprocess
import logging
import time
from collections import deque
from argparse import ArgumentParser
from huawei_lte_api.Connection import Connection
from huawei_lte_api.Client import Client
from huawei_lte_api.enums.client import ResponseEnum
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Initialize logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)


def ping(host):
    """
    Check if a host is reachable via ping.
    """
    command = ['ping', '-c', '1', host]
    return subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def reboot_modem(client):
    """
    Reboot the modem via the Huawei LTE API.
    """
    if client.device.reboot() == ResponseEnum.OK.value:
        logging.info('Reboot requested successfully')
    else:
        logging.error('Error')


def signal_handler(signum, frame):
    """
    Handle signals from the operating system.
    """
    logging.info("Received termination signal. Exiting gracefully.")
    exit(0)


def send_discord_message(webhook_url, content):
    """
    Send a message to a Discord webhook.
    """
    data = {
        "content": content
    }
    response = requests.post(webhook_url, json=data)

    if response.status_code == 204:
        logging.info("Notification sent to Discord")
    else:
        logging.error(f"Failed to send notification to Discord. Status code: {response.status_code}")


def delayed_send_discord_message(webhook_url, content, delay):
    """
    Send a message to a Discord webhook after a delay.
    """
    def send_after_delay():
        time.sleep(delay)
        send_discord_message(webhook_url, content)

    threading.Thread(target=send_after_delay).start()


# Load environment variables
modem_url = os.getenv('MODEM_URL')
modem_username = os.getenv('MODEM_USERNAME')
modem_password = os.getenv('MODEM_PASSWORD')
target_ip = os.getenv('TARGET_IP')
ping_interval = int(os.getenv('PING_INTERVAL'))
max_reboots = int(os.getenv('MAX_REBOOTS'))
reboot_interval = int(os.getenv('REBOOT_INTERVAL'))
discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')


# Parse command line arguments
parser = ArgumentParser()
parser.add_argument('url', type=str, nargs='?', default=modem_url,
                    help='The URL to access the modem\'s web interface. Can also be set with the MODEM_URL environment variable.')
parser.add_argument('--username', type=str, default=modem_username,
                    help='The username for the modem\'s web interface. Can also be set with the MODEM_USERNAME environment variable.')
parser.add_argument('--password', type=str, default=modem_password,
                    help='The password for the modem\'s web interface. Can also be set with the MODEM_PASSWORD environment variable.')
parser.add_argument('--target_ip', type=str, default=target_ip, help='The target IP address to ping')
parser.add_argument('--interval', type=int, default=ping_interval, help='The interval between pings in seconds')
parser.add_argument('--max_reboots', type=int, default=max_reboots, help='The maximum number of reboots within the reboot_interval')
parser.add_argument('--reboot_interval', type=int, default=reboot_interval, help='The time frame (in seconds) for limiting the number of reboots')


args = parser.parse_args()


if args.url is None:
    print("Error: The modem URL must be provided either as a command line argument or via the MODEM_URL environment variable.")
    exit(1)

reboots = 0
reboot_times = []
backoff = 1

# Register signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

from huawei_lte_api.exceptions import ResponseErrorLoginRequiredException

import time
from collections import deque
from huawei_lte_api.Client import Client
from huawei_lte_api.Connection import Connection
from huawei_lte_api.exceptions import ResponseErrorLoginRequiredException

def login_modem(connection):
    client = Client(connection)
    try:
        client.user.login(args.username, args.password)
        return client
    except Exception as e:
        logging.error(f"Login error: {e}")
        return None

def is_modem_responding(client, connection, max_retries=3, retry_interval=5):
    for _ in range(max_retries):
        try:
            device_info = client.device.information()
            if device_info:
                return True
            else:
                return False
        except ResponseErrorLoginRequiredException:
            logging.warning("Re-authenticating with the modem")
            client = login_modem(connection)
            if client is None:
                exit(1)
            return is_modem_responding(client, connection)
        except Exception as e:
            logging.error(f"Error checking modem response: {e}")
            time.sleep(retry_interval)
    return False

def establish_connection(url, max_retries=3, retry_interval=5):
    for _ in range(max_retries):
        try:
            return Connection(url)
        except Exception as e:
            logging.error(f"Error establishing connection: {e}")
            time.sleep(retry_interval)
    return None

reboot_times = deque(maxlen=args.max_reboots)

# Establish the initial connection
connection = establish_connection(args.url)
if connection is None:
    exit(1)
client = login_modem(connection)

while True:
    if not ping(args.target_ip):
        logging.warning(f"Ping to {args.target_ip} failed.")
        current_time = time.time()

        if len(reboot_times) < args.max_reboots or (current_time - reboot_times[0]) > args.reboot_interval:
            try:
                if is_modem_responding(client, connection):
                    reboot_modem(client)
                    reboot_times.append(current_time)
                    # Send a delayed message to the Discord webhook
                    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
                    if webhook_url:
                        delay_seconds = 5 * 60  # 5 minutes in seconds
                        delayed_send_discord_message(webhook_url, f"Modem at {args.url} rebooted due to ping failure to {args.target_ip}", delay_seconds)
                    # Wait for the modem/router to restart properly
                    time.sleep(60 * backoff)
                    # Implement exponential backoff with a maximum of 15 minutes
                    backoff = min(backoff * 2, 15)
            except ResponseErrorLoginRequiredException:
                logging.warning("Re-authenticating with the modem")
                client = login_modem(connection)
                if client is None:
                    exit(1)
                reboot_modem(client)
            except Exception as e:
                logging.error(f"Error during reboot: {e}")
        else:
            logging.warning("Maximum number of reboots reached. Skipping reboot.")
    else:
        logging.info(f"Ping to {args.target_ip} successful.")
        backoff = 1

    time.sleep(args.interval)