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


Bài toán: Cho một DataFrame (bảng dữ liệu), khi serialize từng hàng thành LLM prompt, các hàng liên tiếp có thể dùng chung **prefix cache** nếu các giá trị cột đầu giống nhau. Hãy **sắp xếp lại thứ tự cột và hàng** để tối đa hóa prefix cache hit.

`hit(row) = Σ len(value)² với mọi cột khớp liên tiếp từ đầu với hàng trước

Score: `combined = 0.95 × avg_hit_rate + 0.05 × (12 − min(12, runtime)) / 12`