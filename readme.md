Python script to reboot a Huawei LTE routeur when a defined IP to ping is not responding anymore.
The script then reboot the routeur and send an alert to Discord with a webhook.

See .env file to define the variables.

You can also run the code inside a container with the provided Dockerfile.

docker build -t routeur-monitor .
docker run --env-file .env --name routeur-monitor-container routeur-monitor


I am using the huawei-lte-api API to send the reboot command to the routeur, this API is compatible with multiple Huawei LTE routeur.

https://github.com/Salamek/huawei-lte-api