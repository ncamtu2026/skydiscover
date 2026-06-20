
## Self-Evolving Multi-Agent Systems via Decentralized Memory

* link: https://arxiv.org/pdf/2605.22721
* multi agents, mỗi agent chia làm 2 pool:
	* exploitation pool: retrieive knowledge from past trajectories -> local walk
	* exploration pool: temporary buffer cho current task để gen new idea (ram) -> LLM prior
	* họ claim là giúp đạt được global reachability
	* Mem lưu thông tin:
		* trajectory
		* comment: self comment (kiểu tại sao quyết định vây) -> not only what was solved, but also how was solved and who did solve?
* DECENT-MEM:
	* cho LLM chọn weight để explore hay exploit, exploit thì retrieve top k từ DB, nhưng phải vượt qua ngưỡng cosine similarity, không thì fallback về explore với assumption là không có memory phù hợp, explore tự sinh ra context mới từ LLM làm memory cho lần chạy kế.
* Memory Update:
	* không chỉ có evaluate về score mà còn cho LLM evaluate đưa ra feedback
	* Lấy score giữa 2 stage để cập nhật trọng số cho explore hay exploit, explore tốt thì giảm trọng số exploit, explore tệ thì tăng trọng số exploit, còn exploit như nào tự thân vận động, nói chung chỉ chỉnh tham số exploit.