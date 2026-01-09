# services/exam_rules.py

CERT_CATALOG = {
    "人身": {
        "subjects": {
            "保險法規": "bank/人身/人身_保險法規.xlsx",
            "保險實務": "bank/人身/人身_保險實務.xlsx",
        }
    },
    "投資型": {
        "subjects": {
            "法令規章": "bank/投資型/投資型_法令規章.xlsx",
            "投資實務": "bank/投資型/投資型_投資實務.xlsx",
        }
    },
    "外幣": {
        "subjects": {
            "外幣": "bank/外幣/外幣.xlsx",
        }
    },
}

MOCK_SPECS = {
    "人身": {
        "mode": "total+min_each",
        "pass_total": 140,
        "pass_min_each": 60,
        "sections": [
            {"name": "保險法規", "n_questions": 100, "time_min": 80},
            {"name": "保險實務", "n_questions": 50,  "time_min": 60},
        ],
    },
    "投資型": {
        "mode": "total+min_each",
        "pass_total": 140,
        "pass_min_each": 60,
        "sections": [
            {"name": "法令規章", "n_questions": 50,  "time_min": 50},
            {"name": "投資實務", "n_questions": 100, "time_min": 100},
        ],
    },
    "外幣": {
        "mode": "single",
        "pass_score": 70,
        "sections": [
            {"name": "外幣", "n_questions": 50, "time_min": 60},
        ],
    },
}
