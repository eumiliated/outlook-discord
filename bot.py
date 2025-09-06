import requests
import time

WEBHOOK_URL = "https://discord.com/api/webhooks/1413774501312729149/kP-3sw8glZCreCL3mlNoNZVo9-msbsbhcl6O3zplTfdwd4vsT_MIAeXewoHEoVOERYUC"  # replace with your webhook

def send_message(msg):
    payload = {"content": msg}
    response = requests.post(WEBHOOK_URL, json=payload)
    if response.status_code == 204:
        print("Message sent!")
    else:
        print(f"Failed to send: {response.status_code}, {response.text}")

if __name__ == "__main__":
    while True:
        send_message("✅ Hello from Heroku! Your bot.py is running.")
        time.sleep(60)  # wait 1 minute
