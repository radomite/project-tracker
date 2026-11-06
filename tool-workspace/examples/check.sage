R.<x> = PolynomialRing(QQ)
assert (x^2 - 1).factor().value() == (x - 1) * (x + 1)
print("SageMath exact polynomial computation passed.")
