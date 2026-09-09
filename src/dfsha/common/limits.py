"""Límites compartidos; un bloque no equivale a un mensaje gRPC."""
BLOCK_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 256 * 1024
WRITE_BYTES = 16 * 1024 * 1024
DIAGNOSTIC_BYTES = 64 * 1024 * 1024
MESSAGE_BYTES = 1024 * 1024
GRPC_OPTIONS = (
    ("grpc.max_receive_message_length", MESSAGE_BYTES),
    ("grpc.max_send_message_length", MESSAGE_BYTES),
    ("grpc.enable_retries", 0),  # La aplicación decide sobre intención/resultado.
)
