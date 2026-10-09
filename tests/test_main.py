"""Tests unitarios de la lógica sin cámara ni modelo: geometría, filtro de clases y webhook."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import main


@pytest.fixture(autouse=True)
def fixed_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests de un posible .env local."""
    monkeypatch.setattr(main, "TARGET_CLASSES", frozenset({"cup", "cell phone"}))
    monkeypatch.setattr(main, "CONFIDENCE_THRESHOLD", 0.70)


def make_det(class_name: str = "cup", confidence: float = 0.9) -> main.Detection:
    return main.Detection(class_name, confidence, x1=100, y1=100, x2=200, y2=260)


def make_notifier(cooldown_s: float = 5.0) -> tuple[main.WebhookNotifier, MagicMock]:
    notifier = main.WebhookNotifier("http://n8n.test/webhook/x", cooldown_s, timeout_s=1.0)
    session = MagicMock()
    notifier._session = session
    return notifier, session


def test_center_is_bbox_midpoint() -> None:
    assert make_det().center == (150, 180)


@pytest.mark.parametrize(
    ("class_name", "confidence", "expected"),
    [
        ("cup", 0.71, True),
        ("cup", 0.70, False),  # el umbral es estrictamente mayor
        ("cell phone", 0.95, True),
        ("person", 0.99, False),
    ],
)
def test_is_target(class_name: str, confidence: float, expected: bool) -> None:
    assert make_det(class_name, confidence).is_target() is expected


def test_payload_sent_to_webhook() -> None:
    notifier, session = make_notifier()
    assert notifier.try_notify(make_det(confidence=0.87654))
    notifier.close()

    session.post.assert_called_once()
    url = session.post.call_args.args[0]
    payload = session.post.call_args.kwargs["json"]
    assert url == "http://n8n.test/webhook/x"
    assert set(payload) == {"object", "confidence", "x", "y", "timestamp"}
    assert payload["object"] == "cup"
    assert payload["confidence"] == pytest.approx(0.8765)
    assert (payload["x"], payload["y"]) == (150, 180)
    assert payload["timestamp"].endswith("+00:00")


def test_cooldown_is_per_class() -> None:
    notifier, session = make_notifier(cooldown_s=5.0)
    assert notifier.try_notify(make_det("cup"))
    assert not notifier.try_notify(make_det("cup"))
    assert notifier.try_notify(make_det("cell phone"))
    assert notifier.seconds_until_ready("cup") > 0
    notifier.close()
    assert session.post.call_count == 2


def test_cooldown_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([100.0, 106.0])
    monkeypatch.setattr(main.time, "monotonic", lambda: next(clock))
    notifier, session = make_notifier(cooldown_s=5.0)
    assert notifier.try_notify(make_det())
    assert notifier.try_notify(make_det())
    notifier.close()
    assert session.post.call_count == 2


def test_dry_run_without_url_does_not_post() -> None:
    notifier = main.WebhookNotifier("", 5.0, 1.0)
    notifier._session = MagicMock()
    assert notifier.try_notify(make_det())
    notifier.close()
    notifier._session.post.assert_not_called()
