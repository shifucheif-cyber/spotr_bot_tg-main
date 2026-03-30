from services.betting_calculator import get_bet_recommendation
print(get_bet_recommendation('bla bla \n```json\n{"probability": 75, "odds": 1.85}\n```'))
print(get_bet_recommendation('bla bla \n```json\n{"probability": 40, "odds": 2.0}\n```'))
print(get_bet_recommendation('bla bla \n```json\n{"probability": 60, "odds": null}\n```'))