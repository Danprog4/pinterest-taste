"""The taste model: pairwise linear ridge + RBF ranker + nearest-neighbour pull to bangers / push from slop."""
import os
import numpy as np

DEFAULT = os.path.join(os.path.dirname(__file__), "taste_model.npz")


class TasteModel:
    def __init__(self, l2_lin=8.0, gamma=1.2, l2_rbf=0.15):
        self.l2_lin, self.gamma, self.l2_rbf = l2_lin, gamma, l2_rbf
        self.banger = self.slop = None

    def _rbf(self, A, B):
        d = np.sum(A ** 2, 1, keepdims=True) + np.sum(B ** 2, 1, keepdims=True).T - 2.0 * (A @ B.T)
        return np.exp(-self.gamma * np.maximum(0.0, d))

    def fit(self, X_win, X_lose, weights=None, banger=None, slop=None):
        """X_win[i] was preferred over X_lose[i]; rows are vectors from Embedder."""
        w = np.ones(len(X_win), np.float32) if weights is None else np.asarray(weights, np.float32)
        self.W_ref, self.L_ref, self.banger, self.slop = X_win, X_lose, banger, slop
        diff = X_win - X_lose
        Sw = np.diag(w)
        alpha = np.linalg.solve(Sw @ (diff @ diff.T) + self.l2_lin * np.eye(len(diff)), w)
        self.w_primal = diff.T @ alpha
        D = (self._rbf(X_win, X_win) - self._rbf(X_win, X_lose)) - (self._rbf(X_lose, X_win) - self._rbf(X_lose, X_lose))
        self.beta = np.linalg.solve(Sw @ D + self.l2_rbf * len(X_win) * np.eye(len(X_win)), w)
        self.std_lin = float(np.std(X_win @ self.w_primal) + 1e-6)
        self.std_rbf = float(np.std((self._rbf(X_win, self.W_ref) - self._rbf(X_win, self.L_ref)) @ self.beta) + 1e-6)
        return self

    def raw(self, X):
        base = 0.55 * (X @ self.w_primal) / self.std_lin + \
            0.45 * ((self._rbf(X, self.W_ref) - self._rbf(X, self.L_ref)) @ self.beta) / self.std_rbf
        if self.banger is not None and self.slop is not None and len(self.banger) and len(self.slop):
            tb = np.sort(X[:, :3456] @ self.banger[:, :3456].T, axis=1)[:, -6:].mean(1)
            ts = np.sort(X[:, :3456] @ self.slop[:, :3456].T, axis=1)[:, -6:].mean(1)
            return 0.82 * base + 0.18 * (tb - ts) * 4.5
        return base

    def score(self, X):
        """0..1, higher = more to the taste."""
        return 1.0 / (1.0 + np.exp(-1.15 * self.raw(np.asarray(X, np.float32))))

    def save(self, path):
        np.savez_compressed(path, w_primal=self.w_primal.astype(np.float32), beta=self.beta.astype(np.float32),
                            W_ref=self.W_ref.astype(np.float16), L_ref=self.L_ref.astype(np.float16),
                            banger=np.zeros((0, 1)) if self.banger is None else self.banger.astype(np.float16),
                            slop=np.zeros((0, 1)) if self.slop is None else self.slop.astype(np.float16),
                            std_lin=self.std_lin, std_rbf=self.std_rbf, gamma=self.gamma)

    @classmethod
    def load(cls, path=DEFAULT):
        z = np.load(path)
        m = cls(gamma=float(z["gamma"]))
        m.w_primal, m.beta = z["w_primal"], z["beta"]
        m.W_ref, m.L_ref = z["W_ref"].astype(np.float32), z["L_ref"].astype(np.float32)
        m.banger, m.slop = z["banger"].astype(np.float32), z["slop"].astype(np.float32)
        m.std_lin, m.std_rbf = float(z["std_lin"]), float(z["std_rbf"])
        return m
