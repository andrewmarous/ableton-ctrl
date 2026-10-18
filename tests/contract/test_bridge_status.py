import asyncio

from ableton_ctrl.bridge.server import BridgeServer
from ableton_ctrl.bridge.store import GraphStore
from ableton_ctrl.config import BridgeConfig
from ableton_ctrl.contracts import StatusPayload, StatusQuery
from ableton_ctrl.mcp.client import BridgeClient


def test_offline_bridge_status_round_trips_through_client() -> None:
    async def scenario() -> None:
        config = BridgeConfig(port=8765, secret="fixture-secret-that-is-at-least-forty-three-characters")
        server = BridgeServer(host=config.host, port=0, secret=config.secret, store=GraphStore())
        await server.start()
        try:
            client = BridgeClient(config.model_copy(update={"port": server.port}))
            response = await client.request(StatusQuery(type="status"))
            assert response.ok
            assert isinstance(response.result, StatusPayload)
            assert not response.result.live_connected
        finally:
            await server.close()

    asyncio.run(scenario())
