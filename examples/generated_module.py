from decimal import Decimal
from dataclasses import dataclass, field


@dataclass
class CustomerDiscountCalculator:
    customer_id: int = 0
    order_amount: Decimal = Decimal("0")
    discount_rate: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    final_amount: Decimal = Decimal("0")
    is_premium: str = 'N'

    def main_logic(self):
        self.customer_id = 100423
        self.order_amount = Decimal("1500.00")
        if self.order_amount > 1000:
            self.is_premium = 'Y'
            self.discount_rate = Decimal("15")
        else:
            self.discount_rate = Decimal("5")
        self.discount_amount = (
            self.order_amount * self.discount_rate / Decimal("100")
        )
        self.final_amount = self.order_amount - self.discount_amount
        print('CUSTOMER: ', self.customer_id)
        print('FINAL AMOUNT: ', self.final_amount)
        return


def main():
    obj = CustomerDiscountCalculator()
    obj.main_logic()


if __name__ == "__main__":
    main()
