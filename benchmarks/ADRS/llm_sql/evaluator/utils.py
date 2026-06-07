import pandas as pd
from typing import List, Tuple

class TrieNode:
    def __init__(self):
        self.children = {}
        self.end_of_word = False


class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word):
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.end_of_word = True

    def longest_common_prefix(self, word):
        node = self.root
        common_prefix_length = 0
        for char in word:
            if char in node.children:
                common_prefix_length += len(char)
                node = node.children[char]
            else:
                break
        return common_prefix_length

def calculate_length(value):
    val = 0
    if isinstance(value, bool):
        val = 4  # length of 'True' or 'False'
    elif isinstance(value, (int, float)):
        val = len(str(value))
    elif isinstance(value, str):
        val = len(value)
    else:
        val = 0
    return val**2

def evaluate_df_prefix_hit_cnt(df: pd.DataFrame) -> Tuple[int, int]:
    """
    Evaluate the prefix hit count of a DataFrame.

    Each row string is compared against all previously seen rows via a Trie to
    find the longest matching prefix (simulating LLM prompt-cache reuse).
    Processing is sequential because each insertion must precede the next lookup.
    """
    # Build all row strings at once with vectorized ops, then iterate sequentially.
    row_strings = df.fillna("").astype(str).agg("".join, axis=1).tolist()

    trie = Trie()
    total_prefix_hit_count = 0
    total_string_length = sum(len(s) for s in row_strings)

    for row_string in row_strings:
        total_prefix_hit_count += min(len(row_string), trie.longest_common_prefix(row_string))
        trie.insert(row_string)

    total_prefix_hit_rate = total_prefix_hit_count / total_string_length
    assert total_prefix_hit_count <= total_string_length
    print(f"Total string length: {total_string_length}")
    no_cache_pricing = 2.5 / 5  # per 1M if not cached
    cache_pricing = 1.25 / 5  # per 1M if cached
    cached_tokens_pricing = total_prefix_hit_count * cache_pricing / 1e6
    non_cached_tokens_pricing = (total_string_length - total_prefix_hit_count) * no_cache_pricing / 1e6
    print(
        f"Cached tokens pricing = {round(cached_tokens_pricing,2)}, Non-cached tokens pricing = {round(non_cached_tokens_pricing,2)}, total pricing = {round(cached_tokens_pricing + non_cached_tokens_pricing,2)}"
    )
    return total_prefix_hit_count, total_prefix_hit_rate * 100