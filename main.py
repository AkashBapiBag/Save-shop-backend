"""
Top-level entrypoint for Save Shop Backend API.
Allows running via either:
  uvicorn main:app --reload
or:
  uvicorn app.main:app --reload
or:
  python main.py
"""

from app.main import app

if __name__ == "__main__":
    import uvicorn
    # Bind to 0.0.0.0 so physical mobile phones and emulators on the same Wi-Fi can connect
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

