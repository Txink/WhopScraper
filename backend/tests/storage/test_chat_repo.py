def test_chat_message_row_importable() -> None:
    from app.storage.schema import ChatMessageRow

    assert ChatMessageRow.__tablename__ == "chat_messages"
