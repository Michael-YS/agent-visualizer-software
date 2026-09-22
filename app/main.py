from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from app.config import Settings
from app.models import AgentStatus, HealthResponse, PublishResponse
from app.mqtt import MqttPublisher, MqttUnavailable


def create_app(
    settings: Settings | None = None,
    publisher: MqttPublisher | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    resolved_publisher = publisher or MqttPublisher(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resolved_publisher.start()
        try:
            yield
        finally:
            resolved_publisher.stop()

    application = FastAPI(
        title="Agent Monitor Bridge",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        connected = resolved_publisher.is_connected
        return HealthResponse(
            status="ok" if connected else "degraded",
            mqtt_connected=connected,
        )

    @application.post(
        "/v1/agents/state",
        response_model=PublishResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def publish_agent_state(agent_status: AgentStatus) -> PublishResponse:
        try:
            topic = resolved_publisher.publish(agent_status)
        except MqttUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error
        return PublishResponse(accepted=True, topic=topic)

    return application


app = create_app()
