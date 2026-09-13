def step(value, limit):
    return value + 1 if value < limit else 0


if __name__ == "__main__":
    value = 0
    for _ in range(20):
        value = step(value, 3)
        assert 0 <= value <= 3
    print("Toy counter assertions completed")
