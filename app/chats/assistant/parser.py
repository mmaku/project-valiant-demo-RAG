import json
import re
from typing import Iterable, Any
from loguru import logger

from agents.rag.names import RagNames
from api.models.content import Citation
from chats.utils.names import ChatNames

# --- Compiled regex patterns ---
CITATION_PATTERN = re.compile(r"\[(\d+)]")
REFERENCE_PARAGRAPH_START = re.compile(
    re.escape(ChatNames.final_answer_references_header)
)
# regex pattern that matches:
# - start of string, separator, or newline before a reference
# - a number (group 1)
# - one or more spaces
# - the reference text (group 2)
# - stops matching at next separator, newline, or end of text
REFERENCE_SPLITTER = re.escape(ChatNames.final_answer_references_splitter)
REFERENCE_LINE_PATTERN = re.compile(
    rf"(?:^|{REFERENCE_SPLITTER}|\n)\s*(\d+)\s+(.+?)(?={REFERENCE_SPLITTER}|\n|$)",
    re.DOTALL,
)


class ChatParser:
    """Parses LLM output into structured paragraphs and references."""

    @staticmethod
    def _parse_paragraphs(plain_response: str) -> list[str]:
        """
        Extracts and splits the final answer content into paragraphs.

        The function expects the model output structure to contain
        `ChatNames.user_messages_key` with a list of user-assistant messages,
        and the last item being the final answer string, which is cleaned by
        removing `ChatNames.final_answer_prefix` and split using
        `ChatNames.final_answer_paragraph_split`.

        Args:
            plain_response (str): Raw text response from LLM model.

        Returns:
            list[str]: Cleaned paragraphs. Empty paragraphs are removed.

        Raises:
            KeyError: If required keys are missing in `raw_llm_output`.
            TypeError: If the content extracted is not a string.
        """
        if not isinstance(plain_response, str):
            raise TypeError("Expected final answer content to be a string.")

        clean_content = plain_response.replace(
            ChatNames.final_answer_prefix, ""
        ).strip()

        # Split and remove empty fragments
        paragraphs = [
            p.strip()
            for p in clean_content.split(ChatNames.final_answer_paragraph_split)
            if p and p.strip()
        ]
        return paragraphs

    @staticmethod
    def _extract_rag_references(raw_references: dict) -> dict[str, Citation]:
        """
        Extracts a mapping from filename -> Citation produced by the RAG tool.

        Args:
            raw_references: Raw references store from the graph state.

        Returns:
            dict[str, Citation]: Mapping of reference filenames to Citation objects.
                                 Empty dict if not available.
        """
        rag_references = raw_references.get(RagNames.main_references_key)
        if rag_references is None:
            return {}

        if not isinstance(rag_references, dict):
            logger.warning(
                "RAG references mapping is not a dict; returning empty mapping."
            )
            return {}

        # Expect: { "FILE1.pdf": Citation(...) }
        return rag_references

    @staticmethod
    def _parse_reference_paragraph(reference_section: str) -> dict[int, str]:
        """
        Parse a numeric-to-reference mapping from a 'references paragraph'.

        Works with any string as a reference (URLs, document titles, free text, etc.).
        The function is robust to different formats — it tolerates optional headers,
        newlines, and custom separators.

        Example:
            Input:
                "# References\\n1 https://example.com/report<s>2 Some report<s>3 File.pdf"
            Output:
                {1: "https://example.com/report",
                 2: "Some report",
                 3: "File.pdf"}

        Args:
            reference_section: Raw text containing numbered references.

        Returns:
            A dictionary mapping citation numbers to reference strings.
        """
        if not reference_section:
            return {}

        text = reference_section.strip()

        # remove optional heading like "# References" if present
        text = re.sub(
            rf"^\s*{REFERENCE_PARAGRAPH_START}\s*:?\s*", "", text, flags=re.IGNORECASE
        )

        # start parsing from the first digit
        text = re.sub(r"^\D*(?=\d+\s)", "", text, flags=re.DOTALL)

        refs = {}

        matches = REFERENCE_LINE_PATTERN.findall(text)
        if not matches:
            # Fallback: handle plain space-separated or single-line references
            # Example: "1 A.pdf 2 B.pdf 3 C.pdf"
            fallback_pattern = re.compile(r"(\d+)\s+(\D+?)(?=\d+\s|$)", re.DOTALL)
            matches = fallback_pattern.findall(text)

        for num_str, ref in matches:
            try:
                num = int(num_str)
            except ValueError:
                continue
            refs[num] = ref.strip()

        return refs

    @staticmethod
    def _is_reference_paragraph(text: str) -> bool:
        """
        Heuristic check whether the paragraph looks like a reference mapping block.
        """
        # Remove optional "# References" header
        cleaned = re.sub(
            rf"^\s*{REFERENCE_PARAGRAPH_START}\s*(?:\r?\n)*",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        )

        parts = [p.strip() for p in cleaned.split(REFERENCE_SPLITTER) if p.strip()]

        # Regex for "1 anything"
        reference_pattern = re.compile(r"\d+\s*\S+")

        # Check if at least one matches
        return any(reference_pattern.search(p) for p in parts)

    @staticmethod
    def _unique_preserve_order(items: Iterable[Any]) -> list[Any]:
        """Return unique items preserving the original order.

        Works for hashable lsit items and dicts.
        """
        seen: set[str] = set()
        out: list[Any] = []

        for x in items:
            # Create a string representation of the element
            if isinstance(x, dict):
                key = json.dumps(x, sort_keys=True)
            else:
                key = str(x)
            # Add only unseen elements
            if key not in seen:
                seen.add(key)
                out.append(x)
        return out

    @staticmethod
    def _strip_citations(text: str) -> str:
        """
        Remove inline citations like `[1][2][3]` and normalize whitespace.

        Returns:
            str: Cleaned text without citation markers and with normalized spaces.
        """
        without = re.sub(r"(?:\[\d+])+", "", text)
        return without.rstrip()

    def _map_references(
        self,
        answer_paragraphs: list[str],
        answer_refs_map: dict[int, str],
        references_map: dict[str, Citation],
    ) -> list[dict]:
        """
        Resolve inline [<num>] citations in each paragraph into text content blocks
        with Citation annotations.

        Args:
            answer_paragraphs: Paragraphs without the final references block.
            answer_refs_map: Mapping of citation number -> filename.
            references_map: Mapping of filename -> Citation.

        Returns:
            list[dict]: Text content blocks ({"type", "text", "annotations"}).
        """
        results = []

        for para in answer_paragraphs:
            cited_nums = CITATION_PATTERN.findall(para)
            cited_nums = self._unique_preserve_order(cited_nums)

            # Build citation annotations for this paragraph
            annotations = []
            for num_str in cited_nums:
                num = int(num_str)
                name = answer_refs_map.get(num)
                if not name:
                    logger.warning(
                        f"Citation number [{num}] not found in reference map."
                    )
                    continue
                citation = references_map.get(name)
                if citation is not None:
                    annotations.append(citation.model_dump())
                else:
                    logger.warning(f"Empty reference with name: {name}")

            clean_text = self._strip_citations(para)
            annotations = self._unique_preserve_order(annotations)

            results.append(
                {
                    "type": "text",
                    "text": clean_text,
                    "annotations": annotations,
                }
            )

        return results

    def parse_raw_model_output(self, raw_model_output: dict) -> list[dict]:
        """
        Transform raw model output paragraphs and reference map into a structured form.

        Contract:
        - The last paragraph is *expected* to contain numbered references
          in "<num> <filename>" form separated by <ChatNames.final_answer_references_splitter>.
          If it does not, the whole content is treated as answers without references.
        - `ChatNames.references_config_key` should include a mapping of
          "filename" -> "url", but if it's not present, `url` will be "".

        Args:
            raw_model_output: Raw output from LLM service as a dict with model content and references.

        Returns:
            list[dict]: Structured answer paragraphs with resolved references.

        Raises:
            KeyError/TypeError: If the base content cannot be extracted.
        """
        # Extract plain response text
        response_text = raw_model_output[ChatNames.user_messages_key][-1].text
        paragraphs = self._parse_paragraphs(response_text)
        if not paragraphs:
            logger.warning("No paragraphs to parse; returning empty result.")
            return []
        logger.debug(f"Parsed paragraphs: {paragraphs}")

        # Try to interpret the last paragraph as reference mapping
        candidate_ref_section = paragraphs[-1]
        has_ref_block = self._is_reference_paragraph(candidate_ref_section)

        if has_ref_block:
            answer_paragraphs = paragraphs[:-1]
            answer_refs_map = self._parse_reference_paragraph(candidate_ref_section)
        else:
            # Fallback: no reference paragraph; map remains empty
            logger.warning(
                f"No references section in paragraph: {candidate_ref_section}"
            )
            answer_paragraphs = paragraphs[:-1]
            answer_refs_map = {}

        # Extract raw references
        raw_references = raw_model_output.get(ChatNames.references_config_key, {})
        rag_references_map = self._extract_rag_references(raw_references)

        logger.debug(f"Answer paragraphs: {answer_paragraphs}")
        logger.debug(f"Answer reference map: {answer_refs_map}")
        logger.debug(f"RAG references map: {rag_references_map}")
        return self._map_references(
            answer_paragraphs=answer_paragraphs,
            answer_refs_map=answer_refs_map,
            references_map=rag_references_map,
        )
