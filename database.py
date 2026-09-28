<!DOCTYPE html>
<html lang="am">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Digital Pro Ads</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--tg-theme-bg-color, #f4f6f8);
            color: var(--tg-theme-text-color, #1a1a1a);
            margin: 0;
            padding: 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .container {
            width: 100%;
            max-width: 420px;
        }
        .header {
            text-align: center;
            margin-bottom: 20px;
        }
        .header h1 {
            font-size: 22px;
            margin: 0;
            color: var(--tg-theme-button-color, #2481cc);
        }
        .card {
            background-color: var(--tg-theme-secondary-bg-color, #ffffff);
            border-radius: 14px;
            padding: 18px;
            margin-bottom: 14px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
            text-align: center;
        }
        .balance-label {
            font-size: 13px;
            opacity: 0.7;
            margin-bottom: 4px;
        }
        .balance-val {
            font-size: 28px;
            font-weight: 700;
        }
        .btn-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 10px;
        }
        button {
            width: 100%;
            padding: 14px 10px;
            border-radius: 10px;
            border: none;
            background-color: var(--tg-theme-button-color, #2481cc);
            color: var(--tg-theme-button-text-color, #ffffff);
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        button:active {
            opacity: 0.8;
        }
        .btn-full {
            grid-column: span 2;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Digital Pro Ads</h1>
            <p id="user-greeting" style="font-size: 14px; opacity: 0.8; margin-top: 6px;">እንኳን ደህና መጡ!</p>
        </div>

        <div class="card">
            <div class="balance-label">ቀሪ ሂሳብ (Balance)</div>
            <div class="balance-val">0.00 <span style="font-size: 16px;">USDT</span></div>
        </div>

        <div class="card">
            <div class="btn-grid">
                <button onclick="sendAction('📢 Advertise')">📢 Advertise</button>
                <button onclick="sendAction('➕ Add Channel')">➕ Add Channel</button>
                <button onclick="sendAction('💳 Deposit')">💳 Deposit</button>
                <button onclick="sendAction('🏧 Withdraw')">🏧 Withdraw</button>
                <button onclick="sendAction('📊 My Ads')">📊 My Ads</button>
                <button onclick="sendAction('💰 Balance')">💰 Balance</button>
                <button class="btn-full" onclick="sendAction('🤖 AI Chat')">🤖 AI Assistant</button>
            </div>
        </div>
    </div>

    <script>
        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();

        if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
            document.getElementById('user-greeting').innerText = `እንኳን ደህና መጡ፣ ${tg.initDataUnsafe.user.first_name}!`;
        }

        function sendAction(actionText) {
            tg.sendData(actionText);
            tg.close();
        }
    </script>
</body>
</html>
