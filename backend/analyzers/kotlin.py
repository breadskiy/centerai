import tree_sitter_kotlin
from tree_sitter import Language, Parser

KOTLIN = Language(tree_sitter_kotlin.language())


def without_comments(source):
    """Keep byte positions and line breaks so that reported locations remain stable."""
    raw = bytearray(source.encode())
    stack = [Parser(KOTLIN).parse(bytes(raw)).root_node]
    while stack:
        node = stack.pop()
        if "comment" in node.type:
            for i in range(node.start_byte, node.end_byte):
                if raw[i] != 10:
                    raw[i] = 32
        else:
            stack.extend(node.named_children)
    return raw.decode()
