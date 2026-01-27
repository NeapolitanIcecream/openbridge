import uvicorn

from openbridge.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "openbridge.app:app",
        host=settings.openbridge_host,
        port=settings.openbridge_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
