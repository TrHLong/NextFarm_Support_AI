import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from nextfarm_device.api import data_app,chat_app
from nextfarm_device import store

def test_direct_wrong_cabinet_is_denied(monkeypatch):
    monkeypatch.setattr(store,'user_context',lambda t:{'user_id':'alice','role':'farmer'})
    def deny(*args):raise HTTPException(403,'forbidden')
    monkeypatch.setattr(store,'authorize_device',deny)
    c=TestClient(data_app())
    assert c.get('/devices/bob/data?group=sensor_readings',headers={'Authorization':'Bearer a'}).status_code==403

def test_device_id_is_required_and_technician_cannot_chat(monkeypatch):
    c=TestClient(chat_app())
    assert c.post('/chat',json={'message':'độ ẩm'}).status_code==422
    monkeypatch.setattr(store,'user_context',lambda t:{'user_id':'tech','role':'technician'})
    assert c.post('/chat',json={'device_id':'cabinet','message':'hello'},headers={'Authorization':'Bearer t'}).status_code==403

def test_retired_ticket_has_no_write_path():
    assert TestClient(chat_app()).post('/tickets/confirm',json={}).status_code==410
