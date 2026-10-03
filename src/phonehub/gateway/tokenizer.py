from __future__ import annotations

from .events import GatewayEvent


class EventTokenizer:
    """Converts structured gateway events into a compact model-facing token stream.

    The readable form is deliberate for V0.1: it preserves semantics and makes
    debugging possible. A future encoder can map these symbols to integer IDs
    without changing the event schema.
    """

    @staticmethod
    def _clean(value: object) -> str:
        return str(value).replace("<", "[").replace(">", "]").replace("\n", " ")

    def encode(self, event: GatewayEvent) -> list[str]:
        tokens = [
            f"<EVT:{self._clean(event.event_type).upper()}>",
            f"<DEV:{self._clean(event.device_id)}>",
            f"<SRC:{self._clean(event.source).upper()}>",
            f"<T:{self._clean(event.timestamp)}>",
        ]
        if event.state is not None:
            tokens.append(f"<STATE:{self._clean(event.state).upper()}>")

        for key in sorted(event.attributes):
            value = event.attributes[key]
            tokens.append(
                f"<{self._clean(key).upper()}:{self._clean(value)}>"
            )
        return tokens

    def encode_line(self, event: GatewayEvent) -> str:
        return " ".join(self.encode(event))
