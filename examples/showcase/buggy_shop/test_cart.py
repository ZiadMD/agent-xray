from cart import Cart, Item


def test_subtotal_counts_quantity():
    assert Cart([Item("pen", 2.50, qty=4)]).subtotal() == 10.00


def test_coupon_is_a_percentage():
    assert Cart([Item("lamp", 100.00)], coupon_percent=10).discount() == 10.00


def test_free_shipping_starts_at_the_threshold():
    assert Cart([Item("book", 50.00)]).shipping() == 0.0


def test_free_shipping_uses_the_discounted_subtotal():
    assert Cart([Item("shoes", 55.00)], coupon_percent=10).shipping() == 4.99


def test_total_rounds_to_the_nearest_cent():
    assert Cart([Item("mug", 9.99)]).total() == 16.38


def test_an_empty_cart_costs_nothing():
    assert Cart().total() == 0.0
