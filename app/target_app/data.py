"""Fake banking data used by the local target application.

All records are synthetic and exist only to provide a deterministic UI
surface for the computer-use automation assessment.
"""

MEMBERS = {
    "12345": {
        "member_id": "12345",
        "name": "Alex Morgan",
        "status": "Active",
        "joined": "2019-04-18",
        "phone": "(555) 010-1122",
        "email": "alex.morgan@example.test",
        "accounts": [
            {
                "account_id": "CHK-10021",
                "type": "Checking",
                "nickname": "Everyday Checking",
                "status": "Open",
                "current_balance": 2384.42,
                "available_balance": 2219.42,
                "restricted": False,
                "transactions": [
                    {"date": "2026-09-08", "description": "Payroll Deposit", "amount": 2450.00},
                    {"date": "2026-09-07", "description": "Utility Payment", "amount": -164.18},
                    {"date": "2026-09-05", "description": "Card Purchase", "amount": -81.40},
                ],
            },
            {
                "account_id": "SAV-10022",
                "type": "Savings",
                "nickname": "Primary Savings",
                "status": "Open",
                "current_balance": 4250.75,
                "available_balance": 4250.75,
                "restricted": False,
                "transactions": [
                    {"date": "2026-09-02", "description": "Transfer In", "amount": 500.00},
                    {"date": "2026-08-20", "description": "Interest Credit", "amount": 4.12},
                    {"date": "2026-08-15", "description": "Transfer Out", "amount": -250.00},
                ],
            },
        ],
    },
    "67890": {
        "member_id": "67890",
        "name": "Jane Demo",
        "status": "Active",
        "joined": "2022-11-02",
        "phone": "(555) 010-2233",
        "email": "jane.demo@example.test",
        "accounts": [
            {
                "account_id": "SAV-20041",
                "type": "Savings",
                "nickname": "Rainy Day Fund",
                "status": "Open",
                "current_balance": 1840.20,
                "available_balance": 1840.20,
                "restricted": False,
                "transactions": [
                    {"date": "2026-09-01", "description": "Transfer In", "amount": 300.00},
                    {"date": "2026-08-31", "description": "Interest Credit", "amount": 1.52},
                ],
            },
        ],
    },
    "11111": {
        "member_id": "11111",
        "name": "John Sample",
        "status": "Active",
        "joined": "2017-06-23",
        "phone": "(555) 010-3344",
        "email": "john.sample@example.test",
        "accounts": [
            {
                "account_id": "SAV-30061",
                "type": "Savings",
                "nickname": "Reserve Savings",
                "status": "Restricted",
                "current_balance": 9110.00,
                "available_balance": 0.00,
                "restricted": True,
                "transactions": [],
            },
        ],
    },
    "54321": {
        "member_id": "54321",
        "name": "Taylor Reed",
        "status": "Inactive",
        "joined": "2020-01-14",
        "phone": "(555) 010-4455",
        "email": "taylor.reed@example.test",
        "accounts": [
            {
                "account_id": "CHK-40081",
                "type": "Checking",
                "nickname": "Basic Checking",
                "status": "Dormant",
                "current_balance": 96.13,
                "available_balance": 96.13,
                "restricted": False,
                "transactions": [
                    {"date": "2026-06-14", "description": "Card Purchase", "amount": -18.90},
                ],
            },
            {
                "account_id": "SAV-40082",
                "type": "Savings",
                "nickname": "Holiday Savings",
                "status": "Open",
                "current_balance": 630.00,
                "available_balance": 630.00,
                "restricted": False,
                "transactions": [
                    {"date": "2026-07-30", "description": "Transfer In", "amount": 100.00},
                ],
            },
        ],
    },
}


def get_member(member_id: str):
    return MEMBERS.get(member_id)


def get_account(member_id: str, account_id: str):
    member = get_member(member_id)
    if not member:
        return None

    for account in member["accounts"]:
        if account["account_id"] == account_id:
            return account

    return None
