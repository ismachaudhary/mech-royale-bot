# ZoneHunter-v2 — Mech Royale bot

This is a Python bot for the Mech Royale `mechfight/1` protocol.


## Included files
- `bot.py`: bot strategy and action logic
- `mechfight.py`: official Python protocol wrapper from the starter kit
- `Dockerfile`: runtime image definition


## Local protocol check
From this folder, run:


```bash
python3 check/check.py -- python3 -u bot.py
```

This command requires the official `check/check.py` from the starter kit. Passing it checks protocol correctness and response timing, not match strength.
