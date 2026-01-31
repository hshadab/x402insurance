"""
Train a claim classifier and export to ONNX for Jolt Atlas zkML proving.

Architecture: MLP with power-of-2 dimensions (required for SNARK compatibility).
  Input:  [1, 4] — [http_status, body_length, has_server_error, is_empty_body]
  Hidden: Linear(4, 8) -> ReLU
  Output: Linear(8, 2) -> (class 0 = no failure, class 1 = failure)

Uses PyTorch + torch.onnx.export (matching jolt-atlas onnx-tracer format).

Usage:
    pip install torch numpy
    python models/train_claim_model.py
"""
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import hashlib

torch.manual_seed(42)
np.random.seed(42)


class ClaimClassifier(nn.Module):
    """MLP claim classifier: 4 -> 8 -> 2 (power-of-2 dims for SNARK)."""
    def __init__(self):
        super().__init__()
        self.linear1 = nn.Linear(4, 8)
        self.relu = nn.ReLU()
        self.linear2 = nn.Linear(8, 2)

    def forward(self, x):
        x = self.linear1(x)
        x = self.relu(x)
        x = self.linear2(x)
        return x


def generate_training_data(n=5000):
    """Generate labeled claim data matching the failure detection rules."""
    X = []
    y = []

    for _ in range(n):
        status = int(np.random.choice(
            [200, 201, 204, 301, 400, 403, 404, 500, 501, 502, 503, 504],
            p=[0.25, 0.05, 0.05, 0.02, 0.08, 0.05, 0.1, 0.08, 0.02, 0.05, 0.15, 0.10]
        ))

        if 500 <= status <= 504:
            body_length = int(np.random.choice([0, 20, 100, 500]))
        else:
            body_length = int(np.random.randint(0, 100000))

        has_server_error = 1 if 500 <= status <= 504 else 0
        is_empty_body = 1 if body_length == 0 else 0

        # Label: failure if server error OR empty body
        is_failure = 1 if (has_server_error or is_empty_body) else 0

        X.append([float(status), float(body_length), float(has_server_error), float(is_empty_body)])
        y.append(is_failure)

    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int64)


def main():
    print("Training Jolt Atlas claim classifier (4->8->2 MLP)")
    print("=" * 55)

    X_np, y_np = generate_training_data(5000)
    X = torch.from_numpy(X_np)
    y = torch.from_numpy(y_np)

    model = ClaimClassifier()
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.01)

    # Train
    model.train()
    for epoch in range(200):
        optimizer.zero_grad()
        outputs = model(X)
        loss = criterion(outputs, y)
        loss.backward()
        optimizer.step()

        if epoch % 40 == 0:
            with torch.no_grad():
                preds = outputs.argmax(dim=1)
                acc = (preds == y).float().mean().item()
                print(f"  Epoch {epoch:3d}  loss={loss.item():.4f}  acc={acc:.4f}")

    # Final accuracy
    model.eval()
    with torch.no_grad():
        preds = model(X).argmax(dim=1)
        acc = (preds == y).float().mean().item()
    print(f"\nFinal training accuracy: {acc:.4f}")

    # Test cases
    test_cases = [
        ([503, 0, 1, 1], "503 empty body -> failure"),
        ([200, 1000, 0, 0], "200 with body -> no failure"),
        ([500, 500, 1, 0], "500 with body -> failure"),
        ([200, 0, 0, 1], "200 empty body -> failure"),
        ([404, 2000, 0, 0], "404 with body -> no failure"),
    ]
    print("\nTest cases:")
    for features, desc in test_cases:
        inp = torch.tensor([features], dtype=torch.float32)
        with torch.no_grad():
            out = model(inp)
            pred = out.argmax(dim=1).item()
            probs = torch.softmax(out, dim=1)[0]
        print(f"  {desc}: pred={pred}, probs=[{probs[0]:.3f}, {probs[1]:.3f}]")

    # Export to ONNX (jolt-atlas compatible format)
    output_path = "models/claim_classifier.onnx"
    dummy_input = torch.randn(1, 4)

    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        export_params=True,
        opset_version=11,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={
            "input": {0: "batch_size"},
            "output": {0: "batch_size"},
        },
        dynamo=False,
    )

    print(f"\nONNX model exported to {output_path}")
    print("Architecture: Input(4) -> Linear(4,8) -> ReLU -> Linear(8,2) -> Output")
    print("Compatible with: jolt-atlas onnx-tracer (opset 11, power-of-2 dims)")

    with open(output_path, "rb") as f:
        model_hash = hashlib.sha256(f.read()).hexdigest()
    print(f"Model SHA-256: {model_hash}")


if __name__ == "__main__":
    main()
