
## Reflexion
- Feedback:
	- binary environment feedback
	- pre-defined heuristics
	- self-evaluation using LLMs/self-written unit tests
- advantages
	- do not need finetuning
	- semantic feedback
	- explicit and interpretable form of episodic memory
	- explicit hint
- Chốt lại: React + Experience Memory
## Rememberer
- RL-based for decision making task -> is it suitable for discovery task?
- Short term memory: reward (feedback) -> working memory để đưa ra action
- Long term memory: experience, cập nhật thông qua transition ot -> ot+1 (đi kèm action a_t và feedback r_t)
- Có phần estimate value? -> có estimate Q cũng là một điểm đáng để ý
- Bản thân AdaEvolve có estimate value không? -> câu trả lời là không hẳn, nó vẫn bám vào cơ chế khám phá thay vì tối ưu score.
- AdaEvolve:
	- chỉ được fewshot các example kèm score -> implicit score estimation
	- lưu các solution vào island, lấy ra theo cơ chế explore-exploit -> implicit memory experience memory -> experience memory này yếu ở điểm nào?
- Chưa explicit thông tin:
	- mutation nào dẫn tới improvement
	- tại sao solution thất bại
	- Thiếu comment -> cảm giác nên thêm các feedback -> đẩy cho LLM -> lấy thông  tin từ graph như nào?
	- Thiếu estimate score thực sự, bellman update, không có định hướng rõ ràng (mọi thứ hoạt động thông qua sự tiến hóa)
	- Thiếu cơ chế so sánh sự tiến hóa ngắn và dài hạn của 1 solution -> đưa ra update vào memory.
## Retrospex
- Tối ưu decision bằng offline RL, thông qua trajectory -> optimize decision from learning experience

## OmniMem
## Controllable Decoding