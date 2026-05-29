Column & Row Reordering cho Prefix Caching

```sql
SELECT 
  movie_title,
  LLM("Summarize this plot in 5 words: " || plot) as short_summary
FROM movies
WHERE LLM("Is this a romance? Yes/No: " || description) = 'Yes';
```

Truy vấn trên gọi LLM trực tiếp trên mỗi row của table. Đây là pattern thực tế trong relational analytics với LLM (vd Snowflake Cortex, Databricks AI functions, BigQuery ML).

Sau đó LLM sẽ xử lí các câu prompt được serialize từ các cột trong hàng ví dụ như sau:

```sql
Prompt 1: "Describe: title=Toy Story, genre=Animation, year=1995, director=Lasseter"
Prompt 2: "Describe: title=Cars, genre=Animation, year=2006, director=Lasseter"
Prompt 3: "Describe: title=Titanic, genre=Romance, year=1997, director=Cameron"
```

**Vấn đề**: Mỗi row trigger một LLM call → nếu table có 100K rows → 100K LLM calls → **rất đắt và chậm**.

**Kỹ thuật tối ưu**: Prefix KV cache reuse Modern LLM inference engines (vLLM, SGLang) có optimization quan trọng: **prefix caching**. Khi nhiều prompts share cùng prefix, KV cache của prefix đó được reuse → không phải compute lại.

**Insight bài MLSys'25**: Nếu reorder rows + fields trong table sao cho **các prompt gần nhau share prefix nhiều nhất** → prefix cache hit rate (PHR) tăng → inference rẻ hơn. Cụ thể, sau khi nhóm các hàng share một value, thuật toán reorder cột trong nhóm đó để đẩy value chung lên đầu. Nhóm khác có thể có value chung khác → thứ tự cột khác.

Do đó search space naive là: n! × (m!)^n

**Mục tiêu kép**:
- **Maximize PHR** (prefix hit rate) — chất lượng reorder
- **Minimize runtime** của bản thân thuật toán reorder

Bài toán: Cho một DataFrame (bảng dữ liệu), khi serialize từng hàng thành LLM prompt, các hàng liên tiếp có thể dùng chung **prefix cache** nếu các giá trị cột đầu giống nhau. Hãy **sắp xếp lại thứ tự cột và hàng** để tối đa hóa prefix cache hit.

`hit(row) = Σ len(value)² với mọi cột khớp liên tiếp từ đầu với hàng trước

Score: `combined = 0.95 × avg_hit_rate + 0.05 × (12 − min(12, runtime)) / 12`

**Initial Program** - GGR (Greedy Recursive Grouping) logic chính:
1. Đếm số lần xuất hiện của mỗi value trong table
2. Pick value `v_star` maximize `len(v)² × (count(v) - 1)` — value xuất hiện nhiều và dài thì tốt cho prefix sharing
3. Split rows: nhóm có chứa `v_star` (G), nhóm không (R)
4. Reorder columns trong G để `v_star` lên đầu
5. Recurse trên G còn lại và R