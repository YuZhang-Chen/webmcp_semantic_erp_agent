import requests
from requests.auth import HTTPBasicAuth
import os
from dotenv import load_dotenv
import urllib3

load_dotenv()

SAP_URL = os.getenv("SAP_ODATA_BASE_URL")
USER = os.getenv("SAP_USER")
PASSWORD = os.getenv("SAP_PASSWORD")
SAP_CLIENT = os.getenv("SAP_CLIENT")

print("SAP_URL:", repr(SAP_URL))
print("SAP_USER:", repr(USER))
print("PASSWORD loaded:", bool(PASSWORD))
print("SAP_CLIENT:", SAP_CLIENT)

sales_order = "10927"

url = (
    f"{SAP_URL}/API_SALES_ORDER_SRV/"
    f"A_SalesOrder('{sales_order}')"
)

headers = {
    "Accept": "application/json"
}

params = {
    "sap-client": SAP_CLIENT
}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

print("GET:", url)

response = requests.get(
    url,
    params=params,
    headers=headers,
    auth=HTTPBasicAuth(USER, PASSWORD),
    timeout=30,
    verify=False,
)

print("Final URL:", response.url)
print("HTTP status:", response.status_code)
print("WWW-Authenticate:", response.headers.get("WWW-Authenticate"))

if response.ok:
    data = response.json()
    print(data.get("d", data))
else:
    print(response.text)