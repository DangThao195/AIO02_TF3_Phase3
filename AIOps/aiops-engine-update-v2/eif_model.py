"""
Extended Isolation Forest (EIF) — cài đặt thuần NumPy, không phụ thuộc package `eif` gốc
(package đó build lỗi trên môi trường numpy 2.x/Cython hiện tại).

Khác biệt cốt lõi so với Isolation Forest trục-song song (sklearn.IsolationForest):
  - IF gốc: mỗi node chỉ split trên 1 feature tại 1 thời điểm (axis-aligned) → nếu chỉ 1-2
    feature lệch trong khi 16 feature còn lại "điển hình", độ dài đường cô lập không rút
    ngắn được nhiều (đã verify thực nghiệm: tăng cpu_usage gấp 1000 lần không đổi score).
  - EIF (Hariri et al., 2019): mỗi node split bằng một SIÊU PHẲNG NGẪU NHIÊN (random
    hyperplane) kết hợp NHIỀU feature cùng lúc — (x - p) · n < 0 — nên một điểm lệch trên
    TỔ HỢP nhiều chiều (dù mỗi chiều lệch không quá cực đoan) vẫn có thể bị cô lập nhanh hơn
    nhiều so với IF trục-song song.

API tương thích sklearn: fit(X), predict(X) -> {1, -1}, decision_function(X) (dương = bình
thường, âm = bất thường, giống hệt quy ước của sklearn.IsolationForest) để có thể dùng thay
thế trực tiếp trong benchmark/production mà không cần đổi logic gọi ở nơi khác.
"""
import numpy as np


def _c_factor(n: int) -> float:
    """Hệ số chuẩn hoá độ dài đường trung bình của BST với n điểm (giống IF gốc)."""
    if n <= 1:
        return 0.0
    return 2.0 * (np.log(n - 1) + 0.5772156649) - (2.0 * (n - 1) / n)


class _EIFNode:
    __slots__ = ("is_leaf", "size", "n", "p", "left", "right")

    def __init__(self):
        self.is_leaf = True
        self.size = 0
        self.n = None       # normal vector siêu phẳng
        self.p = None       # điểm gốc siêu phẳng
        self.left = None
        self.right = None


class ExtendedIsolationForest:
    def __init__(self, n_estimators=200, max_samples="auto", contamination=0.03,
                 extension_level=None, random_state=42):
        self.n_estimators = n_estimators
        self.max_samples_setting = max_samples
        self.contamination = contamination
        self.extension_level = extension_level  # None = full extension (d-1)
        self.random_state = random_state

        self.trees_ = []
        self.max_samples_ = None
        self.height_limit_ = None
        self.mean_ = None
        self.std_ = None
        self.offset_ = None  # ngưỡng hiệu chỉnh theo contamination (giống sklearn.offset_)

    # ------------------------------------------------------------------
    def _standardize(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean_) / self.std_

    def _build_tree(self, X: np.ndarray, height: int, rng: np.random.Generator) -> _EIFNode:
        node = _EIFNode()
        node.size = len(X)
        if height >= self.height_limit_ or len(X) <= 1:
            node.is_leaf = True
            return node

        d = X.shape[1]
        ext = self.extension_level if self.extension_level is not None else d - 1
        ext = max(0, min(ext, d - 1))

        # Siêu phẳng ngẫu nhiên: chọn (ext+1) chiều tham gia split, còn lại normal=0
        # (ext=0 tương đương axis-aligned IF gốc; ext=d-1 là full-random hyperplane).
        n_vec = np.zeros(d)
        active_dims = rng.choice(d, size=ext + 1, replace=False)
        n_vec[active_dims] = rng.normal(0, 1, size=ext + 1)

        # Điểm gốc p: lấy ngẫu nhiên trong khoảng [min,max] của TỪNG chiều trong node hiện tại
        mins, maxs = X.min(axis=0), X.max(axis=0)
        p_vec = rng.uniform(mins, maxs)

        proj = (X - p_vec) @ n_vec
        left_mask = proj < 0

        # Nếu split suy biến (toàn bộ về 1 phía) -> dừng làm leaf để tránh đệ quy vô hạn
        if left_mask.all() or (~left_mask).all():
            node.is_leaf = True
            return node

        node.is_leaf = False
        node.n = n_vec
        node.p = p_vec
        node.left = self._build_tree(X[left_mask], height + 1, rng)
        node.right = self._build_tree(X[~left_mask], height + 1, rng)
        return node

    def fit(self, X):
        X = np.asarray(X, dtype=float)
        n_samples, n_features = X.shape

        self.mean_ = X.mean(axis=0)
        self.std_ = X.std(axis=0)
        self.std_[self.std_ < 1e-9] = 1e-9  # tránh chia 0 cho feature gần như hằng số
        Xs = self._standardize(X)

        if self.max_samples_setting == "auto":
            self.max_samples_ = min(256, n_samples)
        else:
            self.max_samples_ = min(int(self.max_samples_setting), n_samples)
        self.height_limit_ = int(np.ceil(np.log2(max(self.max_samples_, 2))))

        rng_master = np.random.default_rng(self.random_state)
        self.trees_ = []
        for t in range(self.n_estimators):
            tree_seed = rng_master.integers(0, 2**32 - 1)
            rng = np.random.default_rng(tree_seed)
            idx = rng.choice(n_samples, size=self.max_samples_, replace=False)
            tree = self._build_tree(Xs[idx], 0, rng)
            self.trees_.append(tree)

        # Hiệu chỉnh offset theo contamination (giống sklearn IsolationForest.offset_):
        # tính anomaly score thô trên toàn bộ training set, lấy ngưỡng ở quantile
        # (1 - contamination) làm điểm phân tách Normal/Anomaly.
        raw_scores = self._raw_anomaly_score(Xs)
        self.offset_ = float(np.quantile(raw_scores, 1.0 - self.contamination))
        return self

    # ------------------------------------------------------------------
    def _path_length_single_tree(self, X: np.ndarray, tree: _EIFNode) -> np.ndarray:
        """Vector hoá theo batch: trả về path length cho toàn bộ X qua 1 cây."""
        n = len(X)
        depths = np.zeros(n)
        active_idx = np.arange(n)
        _stack = [(tree, active_idx, 0)]
        while _stack:
            node, idx, depth = _stack.pop()
            if node.is_leaf:
                depths[idx] = depth + _c_factor(node.size)
                continue
            proj = (X[idx] - node.p) @ node.n
            left_mask = proj < 0
            if node.left is not None and left_mask.any():
                _stack.append((node.left, idx[left_mask], depth + 1))
            if node.right is not None and (~left_mask).any():
                _stack.append((node.right, idx[~left_mask], depth + 1))
        return depths

    def _raw_anomaly_score(self, Xs: np.ndarray) -> np.ndarray:
        """EIF anomaly score thô trong [0,1]: càng gần 1 càng bất thường (quy ước gốc EIF)."""
        avg_path = np.zeros(len(Xs))
        for tree in self.trees_:
            avg_path += self._path_length_single_tree(Xs, tree)
        avg_path /= len(self.trees_)
        c_n = _c_factor(self.max_samples_)
        return 2.0 ** (-avg_path / max(c_n, 1e-9))

    # ------------------------------------------------------------------
    def decision_function(self, X):
        """Dương = Normal, Âm = Anomaly — CÙNG QUY ƯỚC với sklearn.IsolationForest để có
        thể dùng thay thế trực tiếp trong mọi pipeline benchmark/production hiện có."""
        X = np.asarray(X, dtype=float)
        Xs = self._standardize(X)
        raw = self._raw_anomaly_score(Xs)
        return self.offset_ - raw

    def predict(self, X):
        return np.where(self.decision_function(X) < 0, -1, 1)
