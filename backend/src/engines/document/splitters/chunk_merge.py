"""碎块合并：按 min_chunk_size 阈值把小碎块并入相邻块（recursive/delimiter 共用）。"""


def merge_small_chunks(
    chunks: list[dict[str, str]],
    min_chunk_size: int,
    chunk_size: int,
) -> list[dict[str, str]]:
    """合并文本长度小于 min_chunk_size 的碎块与相邻块。

    策略：从左到右扫描，小块优先向后合并（与下一个块拼接），
    如果向后合并会超过 chunk_size，则尝试向前合并（与上一个块拼接）；
    末尾碎块（无后继块）也向前合并——此前末块直接保留成检索碎片
    （红队 P2：「向前合并」只在向后合并超限时可达，末块永不前并）。

    Args:
        chunks: 切分器产出的分块列表，每项含 text/source/page/type 与
            以 ``_chunk_`` 结尾的 doc_id。
        min_chunk_size: 碎块判定阈值（调用方保证已夹取到 chunk_size // 2 内）。
        chunk_size: 合并结果的大小上限，超限的合并尝试被跳过。

    Returns:
        合并后的分块列表，doc_id 按新顺序重新编号。
    """
    if not chunks:
        return chunks

    # 提取文本用于合并计算
    texts = [c['text'] for c in chunks]

    # 用合并后的文本重建文档列表，保留第一个块的元数据
    result = []
    chunk_idx = 0
    i = 0
    while i < len(texts):
        current_text = texts[i]
        # 红队 P2：末尾碎块（<min 且无后继块）此前直接保留成检索碎片——
        # 能向前并入上一个结果（受 chunk_size 硬限）时优先前并。
        if (
            len(current_text) < min_chunk_size
            and result
            and len(result[-1]['text'] + "\n" + current_text) <= chunk_size
        ):
            result[-1]['text'] += "\n" + current_text
            i += 1
            continue
        if len(current_text) < min_chunk_size and i + 1 < len(texts):
            combined = current_text + "\n" + texts[i + 1]
            if len(combined) <= chunk_size:
                # 向后合并：两个块合成一个
                result.append({
                    'text': combined,
                    'source': chunks[i]['source'],
                    'page': chunks[i]['page'],
                    'doc_id': f"{chunks[i]['doc_id'].rsplit('_chunk_', 1)[0]}_chunk_{chunk_idx}",
                    'type': chunks[i]['type'],
                })
                chunk_idx += 1
                i += 2
                continue
            else:
                # 向后合并超限，尝试向前合并到最后一个结果
                if result and len(result[-1]['text'] + "\n" + current_text) <= chunk_size:
                    result[-1]['text'] += "\n" + current_text
                    i += 1
                    continue
        # 不需要合并，直接保留
        result.append({
            'text': current_text,
            'source': chunks[i]['source'],
            'page': chunks[i]['page'],
            'doc_id': f"{chunks[i]['doc_id'].rsplit('_chunk_', 1)[0]}_chunk_{chunk_idx}",
            'type': chunks[i]['type'],
        })
        chunk_idx += 1
        i += 1

    return result
