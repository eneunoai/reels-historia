#!/usr/bin/env python3
"""Publica un vídeo como Reel en la Página de Facebook (Graph API de Meta).

Solo usa la biblioteca estándar de Python.

Variables de entorno:
  META_PAGE_TOKEN    Token de acceso de la Página (obligatorio para publicar).
  META_USER_TOKEN    Token de usuario (solo para --list-pages).
  META_PAGE_ID       ID de la Página (o pásalo con --page-id).
  GRAPH_API_VERSION  Versión de la Graph API (por defecto v23.0).

Uso:
  # Ver tus Páginas, sus IDs y sus tokens de página:
  META_USER_TOKEN=... python3 scripts/facebook_reel.py --list-pages

  # Publicar un Reel:
  META_PAGE_TOKEN=... python3 scripts/facebook_reel.py video.mp4 \
      --page-id 1234567890 --description "¿Sabías que...? #historia #españa"

Requisitos del vídeo para Reels: vertical 9:16 (recomendado 1080x1920),
MP4 H.264 + AAC, al menos 3 segundos.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GRAPH = os.environ.get("META_GRAPH_BASE", "https://graph.facebook.com")
RUPLOAD = os.environ.get("META_RUPLOAD_BASE", "https://rupload.facebook.com")
VERSION = os.environ.get("GRAPH_API_VERSION", "v23.0")


class GraphError(RuntimeError):
    pass


def _request(method, url, *, params=None, data=None, headers=None, timeout=600):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    body = data
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise GraphError(f"HTTP {e.code} en {method} {url.split('?')[0]}: {detail}") from None


def list_pages(user_token):
    res = _request("GET", f"{GRAPH}/{VERSION}/me/accounts",
                   params={"fields": "id,name,username,access_token", "access_token": user_token})
    return res.get("data", [])


def publish_reel(page_id, page_token, video_path, description="", wait=True):
    size = os.path.getsize(video_path)
    endpoint = f"{GRAPH}/{VERSION}/{page_id}/video_reels"

    # 1) Iniciar la sesión de subida
    start = _request("POST", endpoint, data={"upload_phase": "start", "access_token": page_token})
    video_id = start.get("video_id")
    if not video_id:
        raise GraphError(f"Respuesta inesperada al iniciar: {start}")
    upload_url = start.get("upload_url") or f"{RUPLOAD}/video-upload/{VERSION}/{video_id}"
    print(f"[1/3] Sesión de subida creada, video_id={video_id}")

    # 2) Subir los bytes del vídeo
    with open(video_path, "rb") as f:
        payload = f.read()
    up = _request("POST", upload_url, data=payload, headers={
        "Authorization": f"OAuth {page_token}",
        "offset": "0",
        "file_size": str(size),
        "Content-Type": "application/octet-stream",
    })
    if not up.get("success"):
        raise GraphError(f"La subida no se confirmó: {up}")
    print(f"[2/3] Vídeo subido ({size / 1e6:.1f} MB)")

    # 3) Finalizar y publicar
    fin = _request("POST", endpoint, data={
        "upload_phase": "finish",
        "video_id": video_id,
        "video_state": "PUBLISHED",
        "description": description,
        "access_token": page_token,
    })
    if not fin.get("success"):
        raise GraphError(f"No se pudo publicar: {fin}")
    print("[3/3] Publicación solicitada; Facebook está procesando el vídeo")

    if wait:
        wait_until_ready(video_id, page_token)
    return video_id


def wait_until_ready(video_id, page_token, timeout=600, every=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = _request("GET", f"{GRAPH}/{VERSION}/{video_id}",
                      params={"fields": "status", "access_token": page_token}).get("status", {})
        status = st.get("video_status")
        print(f"   estado: {status}")
        if status == "ready":
            print(f"Publicado: https://www.facebook.com/reel/{video_id}")
            return st
        if status == "error":
            raise GraphError(f"Facebook rechazó el vídeo: {json.dumps(st, ensure_ascii=False)}")
        time.sleep(every)
    print("Sigue procesándose; revisa la Página en unos minutos.")
    return None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video", nargs="?", help="Ruta al .mp4")
    p.add_argument("--page-id", default=os.environ.get("META_PAGE_ID"))
    p.add_argument("--description", default="", help="Texto del Reel (puede incluir hashtags)")
    p.add_argument("--no-wait", action="store_true", help="No esperar a que termine el procesado")
    p.add_argument("--list-pages", action="store_true", help="Listar tus Páginas (usa META_USER_TOKEN)")
    a = p.parse_args(argv)

    try:
        if a.list_pages:
            tok = os.environ.get("META_USER_TOKEN")
            if not tok:
                p.error("Falta META_USER_TOKEN")
            for pg in list_pages(tok):
                print(f"{pg['id']}\t{pg.get('username', '-')}\t{pg['name']}")
                print(f"   token de página: {pg.get('access_token', '(sin permiso)')}")
            return 0

        if not a.video:
            p.error("Indica el vídeo a publicar")
        if not a.page_id:
            p.error("Falta --page-id o META_PAGE_ID")
        tok = os.environ.get("META_PAGE_TOKEN")
        if not tok:
            p.error("Falta META_PAGE_TOKEN")
        publish_reel(a.page_id, tok, a.video, a.description, wait=not a.no_wait)
        return 0
    except GraphError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
