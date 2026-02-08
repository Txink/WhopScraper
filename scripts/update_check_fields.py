#!/usr/bin/env python3
"""将 data/check.json 中 parsed 改名为 check，check 内只保留指定字段，并移除 status。"""

import json

CHECK_FIELDS = ['timestamp', 'instruction_type', 'symbol', 'price', 'sell_quantity', 'stop_loss_price']

def main():
    path = 'data/check.json'
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for item in data:
        origin = item.get('origin', {})
        parsed = item.get('parsed')
        existing_check = item.get('check')

        def _price_from_parsed(p):
            price = p.get('price')
            if price is not None:
                return price
            pr = p.get('price_range')
            if pr is None:
                return None
            if len(pr) >= 2:
                return (pr[0] + pr[1]) / 2
            if len(pr) == 1:
                return pr[0]
            return None

        # 优先从 parsed 取，否则从已有 check 取；timestamp 用 origin
        if parsed is not None:
            timestamp = origin.get('timestamp')
            instruction_type = parsed.get('instruction_type')
            symbol = parsed.get('symbol')
            price = _price_from_parsed(parsed)
            sell_quantity = parsed.get('sell_quantity')
            stop_loss_price = parsed.get('stop_loss_price')
        elif existing_check is not None:
            timestamp = existing_check.get('timestamp') or origin.get('timestamp')
            instruction_type = existing_check.get('instruction_type')
            symbol = existing_check.get('symbol')
            price = existing_check.get('price')
            sell_quantity = existing_check.get('sell_quantity')
            stop_loss_price = existing_check.get('stop_loss_price')
        else:
            timestamp = origin.get('timestamp')
            instruction_type = symbol = price = sell_quantity = stop_loss_price = None

        # 没有 symbol 则 check 整体设为 null
        if symbol is None:
            item.clear()
            item['origin'] = origin
            item['check'] = None
            continue

        # 值为 null 的字段不写入
        check = {}
        if timestamp is not None:
            check['timestamp'] = timestamp
        if instruction_type is not None:
            check['instruction_type'] = instruction_type
        check['symbol'] = symbol
        if price is not None:
            check['price'] = price
        if sell_quantity is not None:
            check['sell_quantity'] = sell_quantity
        if stop_loss_price is not None:
            check['stop_loss_price'] = stop_loss_price

        item.clear()
        item['origin'] = origin
        item['check'] = check

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print('Done. Total items:', len(data))


if __name__ == '__main__':
    main()
