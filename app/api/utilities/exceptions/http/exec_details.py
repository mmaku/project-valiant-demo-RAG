def http_400_model_provider_len() -> str:
    return "The 'model_provider' field must contain a list with at most one provider"


def http_500_blob() -> str:
    return "Error when manipulating blob"


def http_500_database() -> str:
    return "Error while processing request in the Database"


def http_500_image_bck_removal() -> str:
    return "Error when removing background from image"


def http_500_image_gen() -> str:
    return "Error when generating images"


def http_500_llm() -> str:
    return "Error when running the LLM pipeline"


def http_500_rag_file_delete() -> str:
    return "Error when deleting the file to RAG"


def http_500_rag_file_upload() -> str:
    return "Error when uploading the file to RAG"
