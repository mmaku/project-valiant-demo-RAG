"""
The HTTP 500 Internal Server Error response status code indicates that the server encountered an unexpected condition that prevented it from fulfilling the request.
"""

import fastapi

from api.utilities.exceptions.http.exec_details import (
    http_500_database,
    http_500_llm,
    http_500_image_gen,
    http_500_image_bck_removal,
    http_500_rag_file_upload,
    http_500_rag_file_delete,
    http_500_blob,
)


async def http_500_database_error() -> Exception:
    return fastapi.HTTPException(
        status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=http_500_database(),
    )


async def http_500_llm_error() -> Exception:
    return fastapi.HTTPException(
        status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR, detail=http_500_llm()
    )


async def http_500_image_gen_error() -> Exception:
    return fastapi.HTTPException(
        status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=http_500_image_gen(),
    )


async def http_500_image_background_error() -> Exception:
    return fastapi.HTTPException(
        status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=http_500_image_bck_removal(),
    )


async def http_500_rag_file_upload_error() -> Exception:
    return fastapi.HTTPException(
        status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=http_500_rag_file_upload(),
    )


async def http_500_rag_file_delete_error() -> Exception:
    return fastapi.HTTPException(
        status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=http_500_rag_file_delete(),
    )


async def http_500_blob_error() -> Exception:
    return fastapi.HTTPException(
        status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=http_500_blob(),
    )
