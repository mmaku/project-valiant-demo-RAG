from enum import StrEnum


class RagNames(StrEnum):
    # Used as the references dictionary key for RAG references in the main agent
    main_references_key = "RAG"
    # Used as the references dictionary key for references inside RAG agent
    rag_references_key = "rag_references"
    # Used as the (RAG) references dictionary key for facts that comes from documents
    information_from_documents = "get_information_from_rag_documents"
