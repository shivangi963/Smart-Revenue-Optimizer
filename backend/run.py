"""Start the API:  python run.py   (from inside the backend/ folder)."""
import uvicorn

if __name__ == "__main__":
    print("\n  Smart Revenue Optimizer API -> http://localhost:8000   (docs: http://localhost:8000/docs)\n")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True,
                reload_dirs=["app"])
