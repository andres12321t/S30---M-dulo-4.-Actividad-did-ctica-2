"""Servidor local para la interfaz de simulación del parqueadero."""

from __future__ import annotations

import argparse
import json
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from simulacion_parqueadero import (
    MAX_REPLICATIONS,
    MIN_REPLICATIONS,
    run_and_save,
)


ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / "interfaz_parqueadero.html"
OUTPUT_PREFIX = ROOT / "resultados_parqueadero"
SIMULATION_LOCK = threading.Lock()
DOWNLOADS = {
    "resultados_parqueadero_resumen.csv",
    "resultados_parqueadero_replicas.csv",
    "resultados_parqueadero_convergencia.png",
    "resultados_parqueadero_antes_despues.png",
}


class ParkingRequestHandler(BaseHTTPRequestHandler):
    server_version = "ParkingQueueSimulation/1.0"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(
                200,
                HTML_PATH.read_bytes(),
                "text/html; charset=utf-8",
            )
            return

        if path.startswith("/files/"):
            file_name = path[len("/files/"):]
            if file_name not in DOWNLOADS:
                self._send_json(404, {"error": "Archivo no disponible."})
                return
            file_path = ROOT / file_name
            if not file_path.is_file():
                self._send_json(
                    404,
                    {"error": "Ejecute la simulación para generar este archivo."},
                )
                return
            content_type = (
                "image/png"
                if file_path.suffix == ".png"
                else "text/csv; charset=utf-8"
            )
            self._send(200, file_path.read_bytes(), content_type)
            return

        self._send_json(404, {"error": "Ruta no encontrada."})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/simulate":
            self._send_json(404, {"error": "Ruta no encontrada."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Longitud de solicitud inválida."})
            return
        if content_length < 1 or content_length > 10_000:
            self._send_json(413, {"error": "Tamaño de solicitud no permitido."})
            return

        try:
            request_data = json.loads(
                self.rfile.read(content_length).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "El cuerpo debe ser JSON válido."})
            return
        if not isinstance(request_data, dict):
            self._send_json(400, {"error": "Se esperaba un objeto JSON."})
            return

        max_replicates = request_data.get("maxReplicates", 200)
        seed = request_data.get("seed", 2026)
        if (
            not isinstance(max_replicates, int)
            or isinstance(max_replicates, bool)
            or not MIN_REPLICATIONS <= max_replicates <= MAX_REPLICATIONS
            or max_replicates % 10 != 0
        ):
            self._send_json(
                400,
                {
                    "error": (
                        f"El máximo de réplicas debe ser múltiplo de 10 "
                        f"entre {MIN_REPLICATIONS} y {MAX_REPLICATIONS}."
                    )
                },
            )
            return
        if not isinstance(seed, int) or isinstance(seed, bool):
            self._send_json(400, {"error": "La semilla debe ser un entero."})
            return

        try:
            with SIMULATION_LOCK:
                data = run_and_save(
                    max_replicates,
                    seed,
                    str(OUTPUT_PREFIX),
                )
        except Exception:
            self.log_error(
                "Error al ejecutar la simulación:\n%s",
                traceback.format_exc(),
            )
            self._send_json(
                500,
                {
                    "error": (
                        "No se pudo completar la simulación. "
                        "Revise la consola donde inició app_parqueadero.py."
                    )
                },
            )
            return
        self._send_json(200, data)

    def log_message(self, format_string: str, *args) -> None:
        print(f"[web] {self.address_string()} - {format_string % args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interfaz local para el modelo de parqueadero."
    )
    parser.add_argument("--puerto", type=int, default=8765)
    parser.add_argument(
        "--sin-abrir",
        action="store_true",
        help="No abrir automáticamente el navegador.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.puerto <= 65535:
        raise SystemExit("El puerto debe estar entre 1 y 65535.")

    server = ThreadingHTTPServer(("127.0.0.1", args.puerto), ParkingRequestHandler)
    address = f"http://127.0.0.1:{args.puerto}"
    print(f"Simulación de parqueadero disponible en {address}")
    print("Presione Ctrl+C en esta ventana para detener el servidor.")
    if not args.sin_abrir:
        threading.Timer(0.8, webbrowser.open_new_tab, args=(address,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando la aplicación.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
