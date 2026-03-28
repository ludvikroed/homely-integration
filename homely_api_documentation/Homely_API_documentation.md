# Homely API Documentation

Provided by Homely (kundeservice@homely.no) on 02.10.2025.

## Table of Contents

```text
1. SDK  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  2
1.1 General  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  2
1.2 API  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  3
1.2.1 Access Token - API  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  3
1.2.2 Refresh Token - API  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  5
1.2.3 Location - API  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  7
1.2.4 Home - API  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  9
1.2.5 Error responses  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  15
1.3 WebSocket  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  16
1.4 Components and data types  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  17
1.4.1 Devices  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  17
1.4.2 Locations  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  17
1.4.3 Sensor Values  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  18
1.5 Data Types  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  19
1.5.1 UUID  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  19
1.5.2 DateTime  . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .  19
```

## 1. SDK

The SDK is designed so that Homely users can develop their own smart-home app solutions. All you need is to connect your solution to the REST-API, authenticate, and start receiving live events from your sensors through a WebSocket connection.

With the use of standard REST-API and WebSockets, this SDK can be implemented with all third-party app builders or modern developer tools. E.g. Node Red, Homey, Java, Javascript, .Net, etc.

### 1.1 General

The SDK-API's makes it possible for users to subscribe to live-data from a set of their private sensors. Sensor data available through the API is:

- HAN-plug (current and total consumption)
- Alarm state
- Temperature
- Door/window status (open/closed)

The API provides real-time data through API's and web socket, and provide these as JSON objects to the Smart Home Central. The list below shows an overall description of the process from connecting the Smart Home Central, to real-time data is received through the API's on the Safe4 Onesti IOT platform:

1. Get Access Token: The Smart Home Central call API for authentication (`Access Token - API`)
   The user is authenticated by using the same username and password as they use in the Homely app, and receives a time limited Access Token.
2. Get available Locations: After authentication, the user can query a list of all locations where the user is either registered as an ADMIN or OWNER (`Location - API`)
3. Get sensor states from Location: Based on the list of available locations for the user, the user can get the current state for one or more devices for a location (`Home - API`)
4. Get live updates from sensors: The user can then choose to subscribe to real-time data from one or more locations (`WebSocket`)
   The web socket then provides the Smart Home Central with real-time data.
5. Get refresh-token: When the time limit for the Access Token is reached, an updated token can be retrieved using the refresh token (`Refresh Token - API`)

## 1.2 API

### API URL's

- `https://sdk.iotiliti.cloud/homely/oauth/token`
- `https://sdk.iotiliti.cloud/homely/locations`
- `https://sdk.iotiliti.cloud/homely/home/{locationId}`

All data from these API's is by default in English, except for manually set names for the location and sensors.

### 1.2.1 Access Token - API

| Field | Value |
| --- | --- |
| URL | `POST /homely/oauth/token` |
| Request Body | Se request body parameters table below. |
| Response | See response body parameters table below. |

This end-point is for retrieving an Access Token. This Token is necessary to gain access to the other API's in Homely SDK.

#### POST Request Body Parameters

| Field Name | Type | JSON Type | Method | Description |
| --- | --- | --- | --- | --- |
| `username` (Required) | String | string | POST | the same e-mail address as used in the Homely app |
| `password` (Required) | String | string | POST | the same password as used in the Homely app |

#### POST Request example body parameters

```json
{
        "username": "testhomelyapi@safe4.com",
        "password": "ThisIsValidPassword12!"
}
```

#### POST Response example

```json
{
    "access_token":
"eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJvQXM5RVdaQ0Q2RG44ei1
WNy1pd0RDc0FsaTgxcWFTc
      FdFUFJPS0l4NWRrIn0.
eyJqdGkiOiI0NDEzNDI1Ni0wMWFlLTQyNTctYjJkZC0zNzZlMDdkZjg3NDgiLCJleHAiOjE2
NDY4MzE4NzEsIm5iZiI6MCwia
WF0IjoxNjQ2ODMxODExLCJpc3MiOiJodHRwOi8va2V5Y2xvYWsub25lc3RpLmF3cy5uZXVyb
3N5cy5wcm8vYXV0aC9yZWFsbXMvbWFzdGVyIiwic3ViIjoi
YmZjMWRjZDMtMmY5Zi00N2RkLWEwYTctYzRlYWEyODgyMWMwIiwidHlwIjoiQmVhcmVyIiwi
YXpwIjoiYWRtaW4tY2xpIiwiYXV0aF90aW1lIjowLCJzZXN
zaW9uX3N0YXRlIjoiZWJjNTExZTctMGE1My00MGM0LWE2YTYtOTVlZmQ1YzgyZjUzIiwiYWN
yIjoiMSIsInNjb3BlIjoiIiwibmFtZSI6IlRlc3QgSG9tZW
x5QVBJIiwicHJlZmVycmVkX3VzZXJuYW1lIjoidGVzdGhvbWVseWFwaSIsImdpdmVuX25hbW
UiOiJUZXN0IiwiZmFtaWx5X25hbWUiOiJIb21lbHlBUEkiL
      CJlbWFpbCI6InRlc3Rob21lbHlhcGlAbmV1cm9zeXMuY29tIn0.
iiccbzXxbmOTEPvF0dFs1KDxND4mVVNWYp4TMoguTM6Z07U6Py6QGfFiPsiz4hQNMzTC
A3ekFg9Re97rv0OJpgAE3hPfzmZrOaUFi4tMsphCdkCDLKPcXSmyVzMhaDAPovgbtGUjYL4U
w5s1P7Cc563T0Wanbdv4ZWNCpalWgQdKNdaP9U4sFiv52n6
B2GoqNH6XjkRz6IYk4lDvRwB_uNtjDT3GszulDI5IVwgVkQwlFxXzARFpq9u6j49AsEwWA1Q
AVN-4L-bWeNBoc7uLDJoo7oWwhQ4Z3cncu7aK7Rk9jTB2G7
      0cdu3mEoQZ5BiI61M5vTRbuii9wGIEsNer-w",
    "expires_in": 60,
    "refresh_expires_in": 1800,
    "refresh_token":
"eyJhbGciOiJIUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICI5ZDNkMWY5Yy01YjA3LTR
hY2YtYmFlYy0xZjI1MDBlOT
      ZjMzUifQ.
eyJqdGkiOiI3MTQxMWQ4OC0wNmQ5LTRhNmYtYWQxMS0yMDhiM2ZhYzlkZmEiLCJleHAiOjE2
NDY4MzM2MTEsIm5iZiI6MCwiaWF0IjoxNjQ2ODMx
ODExLCJpc3MiOiJodHRwOi8va2V5Y2xvYWsub25lc3RpLmF3cy5uZXVyb3N5cy5wcm8vYXV0
aC9yZWFsbXMvbWFzdGVyIiwiYXVkIjoiaHR0cDovL2tleWNsb
2FrLm9uZXN0aS5hd3MubmV1cm9zeXMucHJvL2F1dGgvcmVhbG1zL21hc3RlciIsInN1YiI6I
mJmYzFkY2QzLTJmOWYtNDdkZC1hMGE3LWM0ZWFhMjg4MjFjMC
IsInR5cCI6IlJlZnJlc2giLCJhenAiOiJhZG1pbi1jbGkiLCJhdXRoX3RpbWUiOjAsInNlc3
Npb25fc3RhdGUiOiJlYmM1MTFlNy0wYTUzLTQwYzQtYTZhNi0
      5NWVmZDVjODJmNTMiLCJzY29wZSI6IiJ9.
2MrfnYK9lgESi06oANeauY_1KyeOCQpa5jBBgCsN0Vs",
    "token_type": "bearer",
    "not-before-policy": 1618215605,
    "session_state": "ebc511e7-0a53-40c4-a6a6-95efd5c82f53",
    "scope": ""
}
```

### 1.2.2 Refresh Token - API

| Field | Value |
| --- | --- |
| URL | `POST /homely/oauth/refresh-token` |
| Request Body | Se request body parameters table below. |
| Response | See response body parameters table below. |

The Access Token has a lifetime specified in the filed "expires_in" (seconds). To get a new access key after the previous one expired you can use refresh token key that you have got from field "refresh_token". It also has an expiration time, it is in the field "refresh_expires_in" (seconds).

The Refresh-token API will provide a new Access Token with limited lifetime, and a new Refresh Token.

#### POST Request Body Parameters

| Field Name | Type | JSON Type | Method | Description |
| --- | --- | --- | --- | --- |
| `refresh_token` (Required) | String | string | POST |  |

#### POST Request example body parameters

```json
{
        "refresh_token":
"eyJhbGciOiJIUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICI5ZDNkMWY5Yy01YjA3LTR
hY2YtYmFlYy0xZjI1MDBlOT
      ZjMzUifQ.
eyJqdGkiOiI3MTQxMWQ4OC0wNmQ5LTRhNmYtYWQxMS0yMDhiM2ZhYzlkZmEiLCJleHAiOjE2
NDY4MzM2MTEsIm5iZiI6MCwiaWF0IjoxNjQ2ODMx
ODExLCJpc3MiOiJodHRwOi8va2V5Y2xvYWsub25lc3RpLmF3cy5uZXVyb3N5cy5wcm8vYXV0
aC9yZWFsbXMvbWFzdGVyIiwiYXVkIjoiaHR0cDovL2tleWNsb
2FrLm9uZXN0aS5hd3MubmV1cm9zeXMucHJvL2F1dGgvcmVhbG1zL21hc3RlciIsInN1YiI6I
mJmYzFkY2QzLTJmOWYtNDdkZC1hMGE3LWM0ZWFhMjg4MjFjMC
IsInR5cCI6IlJlZnJlc2giLCJhenAiOiJhZG1pbi1jbGkiLCJhdXRoX3RpbWUiOjAsInNlc3
Npb25fc3RhdGUiOiJlYmM1MTFlNy0wYTUzLTQwYzQtYTZhNi0
      5NWVmZDVjODJmNTMiLCJzY29wZSI6IiJ9.
2MrfnYK9lgESi06oANeauY_1KyeOCQpa5jBBgCsN0Vs"
}
```

#### POST Response example

```json
{
  "access_token":
"eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJvQXM5RVdaQ0Q2RG44ei1
WNy1pd0RDc0FsaTgxcWFTcFdFUFJPS0l4NWRrIn0.
eyJqdGkiOiI3ZDUxYzVlMi04NTMwLTRiOTctOTJkZi1lZDdiZTYyYWM2OTciLCJleHAiOjE2
NDYyMzkxNTYsIm5iZiI6MCwiaWF0IjoxNjQ2MjM5MDk2LCJpc3MiOiJodHRwOi8va2V5Y2xv
YWsub25lc3RpLmF3cy5uZXVyb3N5cy5wcm8vYXV0aC9yZWFsbXMvbWFzdGVyIiwic3ViIjoi
YmZjMWRjZDMtMmY5Zi00N2RkLWEwYTctYzRlYWEyODgyMWMwIiwidHlwIjoiQmVhcmVyIiwi
YXpwIjoiYWRtaW4tY2xpIiwiYXV0aF90aW1lIjowLCJzZXNzaW9uX3N0YXRlIjoiN2ViZjBl
MzQtZjBjYy00MTMyLWI1MzktYTU3NzBmYTJjNmUyIiwiYWNyIjoiMSIsInNjb3BlIjoiIiwi
bmFtZSI6IlRlc3QgSG9tZWx5QVBJIiwicHJlZmVycmVkX3VzZXJuYW1lIjoidGVzdGhvbWVs
eWFwaSIsImdpdmVuX25hbWUiOiJUZXN0IiwiZmFtaWx5X25hbWUiOiJIb21lbHlBUEkiLCJl
bWFpbCI6InRlc3Rob21lbHlhcGlAbmV1cm9zeXMuY29tIn0.
LbKljXL_CsBqjiwZB9ZdgF9mdbY6PeYv6ukXVi5vRAixbsSQUqhTeEQhkyUwYedJw9PqrqGX
Wr0jcisKV6RJXG-Y-4unvtQoM4QKD3T_rYjL1Su6FPTSG-
EQtaKimfRBR80aX9UhaeM3Q1WqIzikvsaEg1SuTw-
Lg3jtTXOIATYcl6KBTKpcPePBZxDx3kMwqcqw6yBjzaBd4ABrc4QOLVl7tzS0nlDA7J7mOJh
lmph5u5i17SdZ6mIB5QmvkhSUJN1ZRxl1nbPQjjO0qFC9hdNOhjBNk9JWKFDxTT-
D4Q6Y4HYOW1da6KqD2Zz4_WRwLdPsiL2E_s0_y48Ccqmyag",
  "expires_in": 60,
  "refresh_expires_in": 1800,
  "refresh_token":
"eyJhbGciOiJIUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICI5ZDNkMWY5Yy01YjA3LTR
hY2YtYmFlYy0xZjI1MDBlOTZjMzUifQ.
eyJqdGkiOiJiOGM2OTc4NS0yYzVlLTRkYjktYjZlOS0wM2E3Y2I3OWM3MTgiLCJleHAiOjE2
NDYyNDA4OTYsIm5iZiI6MCwiaWF0IjoxNjQ2MjM5MDk2LCJpc3MiOiJodHRwOi8va2V5Y2xv
YWsub25lc3RpLmF3cy5uZXVyb3N5cy5wcm8vYXV0aC9yZWFsbXMvbWFzdGVyIiwiYXVkIjoi
aHR0cDovL2tleWNsb2FrLm9uZXN0aS5hd3MubmV1cm9zeXMucHJvL2F1dGgvcmVhbG1zL21h
c3RlciIsInN1YiI6ImJmYzFkY2QzLTJmOWYtNDdkZC1hMGE3LWM0ZWFhMjg4MjFjMCIsInR5
cCI6IlJlZnJlc2giLCJhenAiOiJhZG1pbi1jbGkiLCJhdXRoX3RpbWUiOjAsInNlc3Npb25f
c3RhdGUiOiI3ZWJmMGUzNC1mMGNjLTQxMzItYjUzOS1hNTc3MGZhMmM2ZTIiLCJzY29wZSI6
IiJ9.BTi6q3Ru1EkVpbpQ2NqEafv-gyIN6RCHjOejJMZmHSo",
  "token_type": "bearer",
  "scope": ""
}
```

### 1.2.3 Location - API

| Field | Value |
| --- | --- |
| URL | `GET /homely/locations` |
| Request Body | Se request body parameters table below. |
| Response | See response body parameters table below. |

This API is used for retrieving all Locations (gateways) that the user has access to, as an Owner or Admin.

This API is using Bearer Token as Authentication method. When using this API, the verification is done by using the received Token from Access Token - API.

#### GET Request Header Parameters

| Field Name | Type | JSON Type | Description |
| --- | --- | --- | --- |
| `Authorization` (Required) | String | string | `Authorization: Bearer <token>` |

#### GET Request Header Example

```text
Authorization: Bearer
eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJvQXM5RVdaQ0Q2RG44ei1W
Ny1pd0RDc0FsaTgxcWFTcFdFUFJPS0l4NWRrIn0.
eyJqdGkiOiI0NDEzNDI1Ni0wMWFlLTQyNTctYjJkZC0zNzZlMDdkZjg3NDgiLCJleHAiOjE2
NDY4MzE4NzEsIm5iZiI6MCwiaWF0IjoxNjQ2ODMxODExLCJpc3MiOiJodHRwOi8va2V5Y2xv
YWsub25lc3RpLmF3cy5uZXVyb3N5cy5wcm8vYXV0aC9yZWFsbXMvbWFzdGVyIiwic3ViIjoi
YmZjMWRjZDMtMmY5Zi00N2RkLWEwYTctYzRlYWEyODgyMWMwIiwidHlwIjoiQmVhcmVyIiwi
YXpwIjoiYWRtaW4tY2xpIiwiYXV0aF90aW1lIjowLCJzZXNzaW9uX3N0YXRlIjoiZWJjNTEx
ZTctMGE1My00MGM0LWE2YTYtOTVlZmQ1YzgyZjUzIiwiYWNyIjoiMSIsInNjb3BlIjoiIiwi
bmFtZSI6IlRlc3QgSG9tZWx5QVBJIiwicHJlZmVycmVkX3VzZXJuYW1lIjoidGVzdGhvbWVs
eWFwaSIsImdpdmVuX25hbWUiOiJUZXN0IiwiZmFtaWx5X25hbWUiOiJIb21lbHlBUEkiLCJl
bWFpbCI6InRlc3Rob21lbHlhcGlAbmV1cm9zeXMuY29tIn0.
iiccbzXxbmOTEPvF0dFs1KDxND4mVVNWYp4TMoguTM6Z07U6Py6QGfFiPsiz4hQNMzTCA3ek
Fg9Re97rv0OJpgAE3hPfzmZrOaUFi4tMsphCdkCDLKPcXSmyVzMhaDAPovgbtGUjYL4Uw5s1
P7Cc563T0Wanbdv4ZWNCpalWgQdKNdaP9U4sFiv52n6B2GoqNH6XjkRz6IYk4lDvRwB_uNtj
DT3GszulDI5IVwgVkQwlFxXzARFpq9u6j49AsEwWA1QAVN-4L-
bWeNBoc7uLDJoo7oWwhQ4Z3cncu7aK7Rk9jTB2G70cdu3mEoQZ5BiI61M5vTRbuii9wGIEsN
er-w
```

#### GET Response example

```json
[
    {
        "name": "Kringsjå ~ 109FD",
        "role": "ADMIN",
        "userId": "697bcd43-2d2b-4a20-a0f0-2918d7c340a7",
        "locationId": "182bb447-8fa3-4fab-aa1a-5f01d15d6b59",
        "gatewayserial": "02000001000109FD"
    },
    {
        "name": "Hytta",
        "role": "ADMIN",
        "userId": "697bcd43-2d2b-4a20-a0f0-2918d7c340a7",
        "locationId": "232bb400-8fa3-4fab-aa1a-5f01d15d6b62",
        "gatewayserial": "02000001000123FD"
    }
]
```

### 1.2.4 Home - API

| Field | Value |
| --- | --- |
| URL | `GET /homely/home/{locationId}` |
| Request Body | Se request body parameters table below. |
| Response | See response body parameters table below. |

This API is used for retrieving the alarm state from a Location (gateway), and detailed information/state from the available sensors at this Location. The Location ID is retrieved by using the Location - API.

This API is using Bearer Token as Authentication method. When using this API, the verification is done by using the received Token from Access Token - API.

#### GET Request URL Parameters

| Field Name | Type | JSON Type | Description |
| --- | --- | --- | --- |
| `locationId` (Required) | String | string | the unique id for the location |

#### GET Request Header Parameters

| Field Name | Type | JSON Type | Description |
| --- | --- | --- | --- |
| `Authorization` (Required) | String | string | `Authorization: Bearer <token>` |

#### GET Request Header Example

```text
Authorization: Bearer
eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJvQXM5RVdaQ0Q2RG44ei1W
Ny1pd0RDc0FsaTgxcWFTcFdFUFJPS0l4NWRrIn0.
eyJqdGkiOiI0NDEzNDI1Ni0wMWFlLTQyNTctYjJkZC0zNzZlMDdkZjg3NDgiLCJleHAiOjE2
NDY4MzE4NzEsIm5iZiI6MCwiaWF0IjoxNjQ2ODMxODExLCJpc3MiOiJodHRwOi8va2V5Y2xv
YWsub25lc3RpLmF3cy5uZXVyb3N5cy5wcm8vYXV0aC9yZWFsbXMvbWFzdGVyIiwic3ViIjoi
YmZjMWRjZDMtMmY5Zi00N2RkLWEwYTctYzRlYWEyODgyMWMwIiwidHlwIjoiQmVhcmVyIiwi
YXpwIjoiYWRtaW4tY2xpIiwiYXV0aF90aW1lIjowLCJzZXNzaW9uX3N0YXRlIjoiZWJjNTEx
ZTctMGE1My00MGM0LWE2YTYtOTVlZmQ1YzgyZjUzIiwiYWNyIjoiMSIsInNjb3BlIjoiIiwi
bmFtZSI6IlRlc3QgSG9tZWx5QVBJIiwicHJlZmVycmVkX3VzZXJuYW1lIjoidGVzdGhvbWVs
eWFwaSIsImdpdmVuX25hbWUiOiJUZXN0IiwiZmFtaWx5X25hbWUiOiJIb21lbHlBUEkiLCJl
bWFpbCI6InRlc3Rob21lbHlhcGlAbmV1cm9zeXMuY29tIn0.
iiccbzXxbmOTEPvF0dFs1KDxND4mVVNWYp4TMoguTM6Z07U6Py6QGfFiPsiz4hQNMzTCA3ek
Fg9Re97rv0OJpgAE3hPfzmZrOaUFi4tMsphCdkCDLKPcXSmyVzMhaDAPovgbtGUjYL4Uw5s1
P7Cc563T0Wanbdv4ZWNCpalWgQdKNdaP9U4sFiv52n6B2GoqNH6XjkRz6IYk4lDvRwB_uNtj
DT3GszulDI5IVwgVkQwlFxXzARFpq9u6j49AsEwWA1QAVN-4L-
bWeNBoc7uLDJoo7oWwhQ4Z3cncu7aK7Rk9jTB2G70cdu3mEoQZ5BiI61M5vTRbuii9wGIEsN
er-w
```

#### GET Response example

```json
{
    "locationId": "182bb447-8fa3-4fab-aa1a-5f01d15d6b59",
    "gatewayserial": "02000001000109FD",
    "name": "Kringsjå ~ 109FD",
    "alarmState": "DISARMED",
    "userRoleAtLocation": "ADMIN",
    "devices": [
        {
            "id": "60566ab4-114b-44f9-b355-b08eae8e2bb8",
            "name": "Motion Sensor Mini",
            "serialNumber": "0015BC001A016A18",
            "location": "Floor 1 - Entrance",
            "online": false,
            "modelId": "e806ca73-4be0-4bd2-98cb-71f273b09812",
            "modelName": "Motion Sensor Mini",
            "features": {
                "alarm": {
                    "states": {
                        "alarm": {
                            "value": true,
                            "lastUpdated": "2022-03-07T10:17:06.109Z"
                        },
                        "tamper": {
                            "value": true,
                            "lastUpdated": "2022-03-07T10:17:12.031Z"
                        }
                    }
                },
                "temperature": {
                    "states": {
                        "temperature": {
                            "value": 20.3,
                            "lastUpdated": "2022-03-07T10:16:23.730Z"
                        }
                    }
                },
                "battery": {
                    "states": {
                        "low": {
                            "value": false,
                            "lastUpdated": "2021-10-22T12:54:34.415Z"
                        },
                        "defect": {
                            "value": false,
                            "lastUpdated": "2021-10-22T12:54:34.444Z"
                        },
                        "voltage": {
                            "value": 2.9,
                            "lastUpdated": "2022-03-07T03:23:20.184Z"
                        }
                    }
                },
                "diagnostic": {
                    "states": {
                        "networklinkstrength": {
                            "value": 87,
                            "lastUpdated": "2022-03-07T10:17:13.992Z"
                        },
                        "networklinkaddress": {
                            "value": "0015BC002C102E91",
                            "lastUpdated": "2022-02-21T12:01:35.472Z"
                        }
                    }
                }
            }
        },
        {
            "id": "93fc76e9-1a1f-4e63-8cf4-963f2e834eaf",
            "name": "ELKO Super TR",
            "serialNumber": "000D6F000D8106CC",
            "location": "",
            "online": true,
            "modelId": "72bb9e84-5bd3-4900-8b2e-0fe706299bf4",
            "modelName": "ELKO Super TR",
            "features": {
                "thermostat": {
                    "states": {
                        "LocalTemperature": {
                            "value": 2380,
                            "lastUpdated": "2022-03-09T13:12:12.871Z"
                        },
                        "AbsMinHeatSetpointLimit": {
                            "value": 5,
                            "lastUpdated": "2022-02-03T14:36:22.076Z"
                        },
                        "AbsMaxHeatSetpointLimit": {
                            "value": 50,
                            "lastUpdated": "2022-02-22T13:19:22.773Z"
                        },
                        "OccupiedCoolingSetpoint": {
                            "value": 2600,
                            "lastUpdated": "2022-02-03T14:36:23.359Z"
                        },
                        "OccupiedHeatingSetpoint": {
                            "value": 2800,
                            "lastUpdated": "2022-03-04T13:57:03.957Z"
                        },
                        "ControlSequenceOfOperation": {
                            "value": 2,
                            "lastUpdated": "2022-02-03T14:36:23.833Z"
                        },
                        "SystemMode": {
                            "value": 1,
                            "lastUpdated": "2022-02-03T14:36:23.960Z"
                        },
                        "mf415": {
                            "value": true,
                            "lastUpdated": "2022-03-08T16:37:39.425Z"
                        },
                        "mf413": {
                            "value": false,
                            "lastUpdated": "2022-02-03T14:36:33.303Z"
                        },
                        "mf412": {
                            "value": false,
                            "lastUpdated": "2022-02-03T14:36:33.043Z"
                        },
                        "mf411": {
                            "value": false,
                            "lastUpdated": "2022-02-03T14:36:32.800Z"
                        },
                        "mf406": {
                            "value": true,
                            "lastUpdated": "2022-02-03T14:39:13.128Z"
                        },
                        "mf419": {
                            "value": 0,
                            "lastUpdated": "2022-02-03T14:36:34.587Z"
                        },
                        "mf418": {
                            "value": 10,
                            "lastUpdated": "2022-02-07T13:25:33.056Z"
                        },
                        "mf417": {
                            "value": 0,
                            "lastUpdated": "2022-02-03T14:36:34.134Z"
                        },
                        "mf416": {
                            "value": "01010601000A52",
                            "lastUpdated": "2022-02-03T14:36:33.859Z"
                        },
                        "mf414": {
                            "value": 28,
                            "lastUpdated": "2022-02-03T14:36:27.325Z"
                        },
                        "mf409": {
                            "value": 55546,
                            "lastUpdated": "2022-02-03T14:36:26.509Z"
                        },
                        "mf408": {
                            "value": 2000,
                            "lastUpdated": "2022-03-08T16:54:34.031Z"
                        },
                        "mf407": {
                            "value": null,
                            "lastUpdated": null
                        },
                        "mf405": {
                            "value": false,
                            "lastUpdated": "2022-02-03T14:36:31.827Z"
                        },
                        "mf404": {
                            "value": 15,
                            "lastUpdated": "2022-02-22T13:19:23.746Z"
                        },
                        "mf403": {
                            "value": "00",
                            "lastUpdated": "2022-02-03T14:36:31.506Z"
                        },
                        "mf402": {
                            "value": null,
                            "lastUpdated": null
                        },
                        "mf401": {
                            "value": 2000,
                            "lastUpdated": "2022-02-22T13:19:22.961Z"
                        }
                    }
                }
            }
        },
        {
            "id": "a8034720-2a17-4b2a-95f4-eec910cdeddf",
            "name": "Flood Alarm",
            "serialNumber": "0015BC0033001BFC",
            "location": "",
            "online": true,
            "modelId": "84ea6e1b-7bc4-4678-ae57-9489c2ab1e7b",
            "modelName": "Flood Alarm",
            "features": {
                "alarm": {
                    "states": {
                        "flood": {
                            "value": false,
                            "lastUpdated": "2021-12-08T13:08:08.242Z"
                        }
                    }
                },
                "temperature": {
                    "states": {
                        "temperature": {
                            "value": 22.8,
                            "lastUpdated": "2022-03-09T12:57:32.980Z"
                        }
                    }
                },
                "battery": {
                    "states": {
                        "low": {
                            "value": false,
                            "lastUpdated": "2021-12-08T13:08:08.173Z"
                        },
                        "voltage": {
                            "value": 2.9,
                            "lastUpdated": "2022-03-09T10:27:25.956Z"
                        }
                    }
                },
                "diagnostic": {
                    "states": {
                        "networklinkstrength": {
                            "value": 83,
                            "lastUpdated": "2022-03-09T13:07:52.617Z"
                        },
                        "networklinkaddress": {
                            "value": "0015BC002C102E91",
                            "lastUpdated": "2022-03-08T00:25:49.935Z"
                        }
                    }
                }
            }
        },
        {
            "id": "1d6d0206-bfcc-4c8b-83f1-c23d7270fe9f",
            "name": "HAN plug",
            "serialNumber": "0015BC001B024D94",
            "location": "Floor 1 - Entrance",
            "online": true,
            "modelId": "45ffe7b0-93d7-4450-be28-51a3efb443ba",
            "modelName": "EMI Norwegian HAN",
            "features": {
                "metering": {
                    "states": {
                        "summationdelivered": {
                            "value": 769670,
                            "lastUpdated": "2022-03-09T13:00:07.206Z"
                        },
                        "summationreceived": {
                            "value": 0,
                            "lastUpdated": "2022-01-26T16:00:02.793Z"
                        },
                        "demand": {
                            "value": 105,
                            "lastUpdated": "2022-03-09T13:13:07.180Z"
                        },
                        "check": {
                            "value": false,
                            "lastUpdated": "2022-01-26T15:31:57.273Z"
                        }
                    }
                },
                "diagnostic": {
                    "states": {
                        "networklinkstrength": {
                            "value": 98,
                            "lastUpdated": "2022-03-09T12:53:34.797Z"
                        },
                        "networklinkaddress": {
                            "value": "0015BC002C102E91",
                            "lastUpdated": "2022-03-07T22:56:38.694Z"
                        }
                    }
                }
            }
        }
    ]
}
```

### 1.2.5 Error responses

When an error occurs, the API will return an error message consisting of error code and error message.

```json
{
  "statusCode": number,
  "message": string | string[]
}
```

`statusCode`: number with HTTP response status code <https://developer.mozilla.org/en-US/docs/Web/HTTP/Status>

`message`: a string or an array of strings with information about the error code

Examples:

Trying to access with a non-valid authorization token:

```json
{
  "statusCode": 401,
  "message": "Unauthorized"
}
```

Missing one request payload param for example password in authentication endpoint:

```json
{
  "statusCode": 400,
  "message": ["password must be a string"]
}
```

Refresh Token has expired:

```json
{
  "statusCode": 400,
  "message": "Refresh token expired"
}
```

User does not have access to the specified location:

```json
{
  "statusCode": 403,
  "message": "User a8dc1a32-9ac4-4ec1-b793-5e7946e389ba has no access
to location 182bb447-8fa3-4fab-aa1a-5f01d15d6b51"
}
```

## 1.3 WebSocket

The purpose of this guide is to set a valid connection to the Homely WebSocket channel using SocketIO. The WebSocket protocol enables continuous communication between your solution and the WebSocket server in SDK.

Address to our WebSocket connection:

```text
//sdk.iotiliti.cloud
```

In addition you have to set an extra header with the authorization token to identify user and location (gateway). Use the same Token as you received through Access Token - API.

```text
//sdk.iotiliti.cloud?locationId={locationId}&token=Bearer{token}
```

Example Connection:

NB: `"JWT"` is replaced by the actual token

```js
const socket = io('//test-sdk.iotiliti.cloud', {
  transportOptions: {
    polling: {
      extraHeaders: {
        Authorization: `Bearer JWT`,
      },
    },
  },
});
```

Example event subscriber:

```js
socket.on('event', function (data) {
  // data.type -> event subject
  // data.payload -> payload
  console.log(data);
});
```

## 1.4 Components and data types

### 1.4.1 Devices

Devices is returned by the Home-API Home, and represents the physical devices/sensors available for the specified location.

| Field Name | Type | JSON Type | Description | Example values |
| --- | --- | --- | --- | --- |
| `id` | UUID | string | unique id for the device | `"182bb447-8fa3-4fab-aa1a-5f01d15d6b59"` |
| `name` | String | string | the manually set name for the device. If the manual name is not set by the owner, then the standard name is shown | `"movement kitchen"` |
| `serialNumber` | String | string | the serial number for the device | `"00158C001A0116A18"` |
| `location` | String | string | displaying the floor and room name if set for the device. If a custom room is added, the custom room name is displayed | `"Floor 1 - Entrance"` |
| `online` | Boolean | boolean |  | `true` or `false` |
| `modelId` | String | string | unique id for the model | `"182bb447-8fa3-4fab-aa1a-5f01d15d6b59"` |
| `modelName` | String | string | displaying the model name | `"Motion Sensor Mini"` |

### 1.4.2 Locations

The location entity represents the physical gateway to which the sensor is connected. If a user has access to more than one gateway, this is represented as an equal amount of location entities.

| Field Name | Type | JSON Type | Description | Example values |
| --- | --- | --- | --- | --- |
| `name` | String | string | the manually set name for the location |  |
| `role` | String | string | users role at the location/gateway | `"ADMIN"` |
| `userId` | UUID | string | unique id for the user | `"182bb447-8fa3-4fab-aa1a-5f01d15d6b59"` |
| `locationId` | UUID | string | unique id for the location | `"182bb447-8fa3-4fab-aa1a-5f01d15d6b59"` |
| `gatewayserial` | String | string | serial number for the gateway | `"02000001000109FD"` |

### 1.4.3 Sensor Values

The tables below shows different status values, and how they can be interpreted.

#### Location

| Device | Field | Example Value | Description |
| --- | --- | --- | --- |
| `gateway/location` | `alarmState` | `DISARMED` |  |
| `gateway/location` | `alarmState` | `ARMED_AWAY` |  |
| `gateway/location` | `alarmState` | `ARMED_NIGHT` |  |
| `gateway/location` | `alarmState` | `ARMED_PARTLY` |  |
| `gateway/location` | `alarmState` | `BREACHED` |  |
| `gateway/location` | `alarmState` | `ALARM_PENDING` |  |
| `gateway/location` | `alarmState` | `ALARM_STAY_PENDING` |  |
| `gateway/location` | `alarmState` | `ARMED_NIGHT_PENDING` |  |
| `gateway/location` | `alarmState` | `ARMED_AWAY_PENDING` |  |

#### Motion Sensor Mini

| Device | Field | Example Value | Description |
| --- | --- | --- | --- |
| `Motion Sensor Mini` | `online` | `false` | the sensor is offline |
| `Motion Sensor Mini` | `online` | `true` | the sensor is online |
| `Motion Sensor Mini` | `features/temperature` | `20.3` | local temperature is 20.3 Celsius |
| `Motion Sensor Mini` | `features/battery/low` | `false` | battery is OK |
| `Motion Sensor Mini` | `features/battery/low` | `true` | battery is low |

#### Window Sensor

| Device | Field | Example Value | Description |
| --- | --- | --- | --- |
| `Window Sensor` | `online` | `false` | the sensor is offline |
| `Window Sensor` | `online` | `true` | the sensor is online |
| `Window Sensor` | `alarm` | `true` | opened |
| `Window Sensor` | `alarm` | `false` | closed |
| `Window Sensor` | `temperature` | `24` | showing current temperature |
| `Window Sensor` | `battery/low` | `false` | battery is OK |
| `Window Sensor` | `battery/low` | `true` | battery is low |

#### ELKO Super TR

| Device | Field | Example Value | Description |
| --- | --- | --- | --- |
| `ELKO Super TR` | `online` | `false` | the sensor is offline |
| `ELKO Super TR` | `online` | `true` | the sensor is online |
| `ELKO Super TR` | `LocalTemperature` | `2370` | showing local temperature (calculated from example: 23.7 Celsius)) |

#### Flood Alarm

| Device | Field | Example Value | Description |
| --- | --- | --- | --- |
| `Flood Alarm` | `online` | `false` | the sensor is offline |
| `Flood Alarm` | `online` | `true` | the sensor is online |
| `Flood Alarm` | `features/alarm/states/flood` | `false` | no flood detected |
| `Flood Alarm` | `features/alarm/states/flood` | `true` | flood detected |

#### HAN Plug

| Device | Field | Example Value | Description |
| --- | --- | --- | --- |
| `EMI Norwegian HAN` | `online` | `false` | the sensor is offline |
| `EMI Norwegian HAN` | `online` | `true` | the sensor is online |
| `EMI Norwegian HAN` | `summationdelivered` | `769750` | Total consumption (calculated from example: 769,8 kWh) |
| `EMI Norwegian HAN` | `demand` | `104` | Current consumption, displayed in watt |

## 1.5 Data Types

### 1.5.1 UUID

A universally unique identifier (UUID) is a 128-bit label used for information in computer systems. The term globally unique identifier (GUID) is also used, often in software created by Microsoft. When generated according to the standard methods, UUIDs are, for practical purposes, unique.

<https://en.wikipedia.org/wiki/Universally_unique_identifier>

UUID Generator

<https://www.uuidgenerator.net/>

### 1.5.2 DateTime

Date and time according the ISO 8601-2:2019 (Extended Format)
