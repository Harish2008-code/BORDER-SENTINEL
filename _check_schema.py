import pymysql
conn = pymysql.connect(host='localhost', user='root', password='4310',
                       database='identity_screening', port=3306,
                       cursorclass=pymysql.cursors.DictCursor)
cur = conn.cursor()
for tbl in ['person', 'passport', 'driving_license', 'visa', 'aadhaar']:
    try:
        cur.execute('DESCRIBE `%s`' % tbl)
        cols = [r['Field'] for r in cur.fetchall()]
        print('%s: %s' % (tbl, cols))
    except Exception as e:
        print('%s: ERROR %s' % (tbl, e))
conn.close()
