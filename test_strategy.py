# -*- coding: utf-8 -*-

from strategy_overnight_t import run_strategy


def main() -> None:
    df = run_strategy(max_count=20)
    print(df.head(20))


if __name__ == "__main__":
    main()
