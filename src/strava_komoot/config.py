from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    strava_client_id: str = ""
    strava_client_secret: str = ""
    komoot_email: str = ""
    komoot_password: str = ""


settings = Settings()
