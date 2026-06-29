from financial_bot.app.domain.bank_learning import normalize_bank_merchant_key


def test_normalize_bank_merchant_key() -> None:
    assert normalize_bank_merchant_key("  BAHETLE_P_QR  ") == "bahetle p qr"
    assert normalize_bank_merchant_key("SBERCHAEVYE") == "sberchaevye"
    assert normalize_bank_merchant_key("Аптека № 7") == "аптека 7"
    assert normalize_bank_merchant_key("qr") == ""
    assert normalize_bank_merchant_key("   ") == ""
