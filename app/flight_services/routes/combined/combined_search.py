from fastapi import APIRouter, HTTPException, Depends
import httpx
import asyncio
import os

router = APIRouter()

# Load API credentials from environment variables
BDFARE_BASE_URL = os.getenv("BDFARE_BASE_URL")
BDFARE_API_KEY = os.getenv("BDFARE_API_KEY")
FLYHUB_BASE_URL = os.getenv("FLYHUB_PRODUCTION_URL")
FLYHUB_USERNAME = os.getenv("FLYHUB_USERNAME")
FLYHUB_API_KEY = os.getenv("FLYHUB_API_KEY")

# Cached token for FlyHub
cached_token = {"token": None, "expires_at": 0}


async def fetch_bdfare_flights(payload):
    """Call BDFare API for flight searching."""
    url = f"{BDFARE_BASE_URL}/AirShopping"
    headers = {"X-API-KEY": BDFARE_API_KEY, "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)


async def fetch_flyhub_flights(payload):
    """Call FlyHub API for flight searching."""
    # Ensure the token is available and not expired
    global cached_token
    if not cached_token["token"] or cached_token["expires_at"] <= asyncio.get_event_loop().time():
        await authenticate_flyhub()

    url = f"{FLYHUB_BASE_URL}AirSearch"
    headers = {
        "Authorization": f"Bearer {cached_token['token']}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)


async def authenticate_flyhub():
    """Authenticate with FlyHub and cache the token."""
    global cached_token
    url = f"{FLYHUB_BASE_URL}Authenticate"
    payload = {"username": FLYHUB_USERNAME, "apikey": FLYHUB_API_KEY}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)

    if response.status_code == 200:
        token_data = response.json()
        cached_token["token"] = token_data["TokenId"]
        cached_token["expires_at"] = asyncio.get_event_loop().time() + 3600  # Assume token validity is 1 hour
    else:
        raise HTTPException(status_code=response.status_code, detail="FlyHub Authentication Failed")


def convert_bdfare_to_flyhub(payload):
    """Convert BDFare request format to FlyHub request format."""
    flyhub_payload = {
        "AdultQuantity": sum(1 for pax in payload["request"]["pax"] if pax["ptc"] == "ADT"),
        "ChildQuantity": sum(1 for pax in payload["request"]["pax"] if pax["ptc"] == "CHD"),
        "InfantQuantity": sum(1 for pax in payload["request"]["pax"] if pax["ptc"] == "INF"),
        "EndUserIp": "103.124.251.147",  # Replace with actual IP
        "JourneyType": "1" if payload["request"]["shoppingCriteria"]["tripType"].lower() == "oneway" else "2",
        "Segments": [
            {
                "Origin": segment["originDepRequest"]["iatA_LocationCode"],
                "Destination": segment["destArrivalRequest"]["iatA_LocationCode"],
                "CabinClass": "1" if payload["request"]["shoppingCriteria"]["travelPreferences"]["cabinCode"].lower() == "economy" else "2",
                "DepartureDateTime": segment["originDepRequest"]["date"]
            }
            for segment in payload["request"]["originDest"]
        ]
    }
    return flyhub_payload


@router.post("/search")
async def combined_search(payload: dict):
    """
    Perform a combined flight search using BDFare and FlyHub APIs.

    Args:
        payload (dict): The flight search request payload in BDFare format.

    Returns:
        dict: Combined flight results from BDFare and FlyHub.
    """
    # Convert BDFare payload to FlyHub payload
    flyhub_payload = convert_bdfare_to_flyhub(payload)

    try:
        # Call both APIs concurrently
        bdfare_task = fetch_bdfare_flights(payload)
        flyhub_task = fetch_flyhub_flights(flyhub_payload)

        bdfare_response, flyhub_response = await asyncio.gather(bdfare_task, flyhub_task)

        # Combine the responses
        combined_results = {
            "bdfare": bdfare_response,
            "flyhub": flyhub_response
        }

        return combined_results

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
