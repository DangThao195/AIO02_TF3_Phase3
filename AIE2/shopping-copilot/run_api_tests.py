import requests
import json

url = 'http://127.0.0.1:8001/api/chat'

test_cases = [
    ('greeting', 'Chao ban'),
    ('search_product', 'Tim kinh thien van duoi 200 do'),
    ('category_filter', 'Co ong nhom nao khong'),
    ('price_filter', 'San pham duoi 50 do'),
    ('multi_filter', 'Kinh thien van tu 100 den 300 do'),
    ('get_categories', 'Co nhung danh muc nao'),
    ('get_product_id', 'Lay product_id cua Starsense Explorer Refractor Telescope'),
    ('get_details', 'Xem chi tiet san pham OLJCESPC7Z'),
    ('get_reviews', 'Review cua Starsense Explorer Refractor Telescope'),
    ('best_reviewed', 'San pham danh gia cao nhat'),
    ('worst_reviewed', 'San pham danh gia thap nhat'),
    ('add_to_cart', 'Them National Park Foundation Explorascope vao gio'),
    ('get_cart', 'Xem gio hang'),
    ('check_cart', 'Co san pham OLJCESPC7Z trong gio khong'),
    ('recommendations', 'San pham tuong tu kinh thien van'),
    ('convert_currency', '100 USD bang bao nhieu VND'),
    ('shipping', 'Phi ship den Da Nang'),
    ('out_of_scope', 'Thoi tiet hom nay the nao'),
]

print('Running tests...')
for name, msg in test_cases:
    r = requests.post(url, json={'message': msg, 'session_id': 'test_' + name, 'user_id': 'test_user'})
    d = r.json()
    status = d.get('status')
    ok = 'PASS' if status in ('ok', 'pending') else 'FAIL'
    print('{}: {} -> {} ({} chars)'.format(ok, name, status, len(d.get('reply', ''))))