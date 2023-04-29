#!/usr/bin/env python3
import os
import time
import signal
import requests
import threading
import subprocess
import logging
from argparse import ArgumentParser
from huawei_lte_api.Connection import Connection
from huawei_lte_api.Client import Client
from huawei_lte_api.enums.client import ResponseEnum
from dotenv import load_dotenv

load_dotenv()

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
target_ips = os.getenv('TARGET_IPS', '').split(',')
ping_interval = int(os.getenv('PING_INTERVAL'))
max_reboots = int(os.getenv('MAX_REBOOTS'))
reboot_interval = int(os.getenv('REBOOT_INTERVAL'))
ping_attempts = int(os.getenv('PING_ATTEMPTS', 3))
reboot_wait = int(os.getenv('REBOOT_WAIT', 120))
discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')

# Parse command line arguments
parser = ArgumentParser()
parser.add_argument('url', type=str, nargs='?', default=modem_url,
                    help='The URL to access the modem\'s web interface. Can also be set with the MODEM_URL environment variable.')
parser.add_argument('--username', type=str, default=modem_username,
                    help='The username for the modem\'s web interface. Can also be set with the MODEM_USERNAME environment variable.')
parser.add_argument('--password', type=str, default=modem_password,
                    help='The password for the modem\'s web interface. Can also be set with the MODEM_PASSWORD environment variable.')
parser.add_argument('--target_ips', type=lambda s: [ip.strip() for ip in s.split(',')], default=target_ips, help='Comma-separated list of target IP addresses to ping')
parser.add_argument('--interval', type=int, default=ping_interval, help='The initial interval between pings in seconds')
parser.add_argument('--max_reboots', type=int, default=max_reboots, help='The maximum number of reboots within the reboot_interval')
parser.add_argument('--reboot_interval', type=int, default=reboot_interval, help='The time frame (in seconds) for limiting the number of reboots')
parser.add_argument('--ping_attempts', type=int, default=ping_attempts, help='The number of consecutive failed pings required before initiating a reboot')
parser.add_argument('--reboot_wait', type=int, default=reboot_wait, help='The waiting time after a reboot in seconds')

args = parser.parse_args()

if args.url is None:
    print("Error: The modem URL must be provided either as a command line argument or via the MODEM_URL environment variable.")
    exit(1)

reboots = 0
reboot_times = []
backoff = 1
successful_pings = 0

# Register signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def login_modem(connection):
    client = Client(connection)
    try:
        client.user.login(args.username, args.password)
        return client
    except Exception as e:
        logging.error(f"Login error: {e}")
        return None

with Connection(args.url) as connection:
    client = login_modem(connection)
    if client is None:
        exit(1)

    while True:
        failed_pings = 0
        for target_ip in args.target_ips:
            if not ping(target_ip):
                logging.warning(f"Ping to {target_ip} failed.")
                failed_pings += 1
            else:
                logging.info(f"Ping to {target_ip} successful.")

        if failed_pings == len(args.target_ips):
            successful_pings = 0
            if failed_pings >= args.ping_attempts:
                current_time = time.time()

                # Remove reboot timestamps older than reboot_interval
                reboot_times = [t for t in reboot_times if (current_time - t) <= args.reboot_interval]

                if len(reboot_times) < args.max_reboots:
                    try:
                        reboot_modem(client)
                        reboot_times.append(current_time)
                        # Send a delayed message to the Discord webhook
                        if discord_webhook_url:
                            delay_seconds = 5 * 60  # 5 minutes in seconds
                            delayed_send_discord_message(discord_webhook_url, f"Modem at {args.url} rebooted due to ping failure to {','.join(args.target_ips)}", delay_seconds)
                        # Wait for the modem/router to restart properly
                        time.sleep(args.reboot_wait * backoff)
                        # Implement exponential backoff with a maximum of 15 minutes
                        backoff = min(backoff * 2, 15)
                    except Exception as e:
                        logging.error(f"Error during reboot: {e}")
                else:
                    logging.warning("Maximum number of reboots reached. Skipping reboot.")
        else:
            successful_pings += 1
            if successful_pings >= args.ping_attempts:
                backoff = 1
                args.interval = min(args.interval * 2, 60)  # Double the interval, but cap at 60 seconds
            else:
                args.interval = max(args.interval // 2, 1)  # Halve the interval, but don't go below 1
        time.sleep(args.interval)