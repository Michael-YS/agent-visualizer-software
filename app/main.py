from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.models import AgentListResponse, AgentStatus, HealthResponse, PublishResponse
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
    web_dir = Path(__file__).parent / "web"
    application.mount("/static", StaticFiles(directory=web_dir), name="static")

    @application.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(web_dir / "index.html", headers={"Cache-Control": "no-store"})

    @application.get("/v1/agents", response_model=AgentListResponse)
    def list_agents(response: Response) -> AgentListResponse:
        response.headers["Cache-Control"] = "no-store"
        agents = resolved_publisher.snapshot()
        return AgentListResponse(
            agents=agents, total=len(agents),
            mqtt_connected=resolved_publisher.is_connected,
        )

    @application.get("/v1/agents/{agent_id}", response_model=AgentStatus)
    def get_agent(agent_id: str, response: Response) -> AgentStatus:
        response.headers["Cache-Control"] = "no-store"
        for agent in resolved_publisher.snapshot():
            if agent.id == agent_id:
                return agent
        raise HTTPException(status_code=404, detail="Agent not found")

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
