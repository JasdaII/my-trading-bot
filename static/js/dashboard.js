// 顯示加載指示器
function showLoading() {
    document.querySelector('.loading-indicator').style.display = 'flex';
}

// 隱藏加載指示器
function hideLoading() {
    document.querySelector('.loading-indicator').style.display = 'none';
}

// 自動更新儀表板數據
function updateDashboard() {
    console.log('正在更新儀表板數據...');
    showLoading();  // 顯示加載指示器
    fetch('/api/dashboard')
        .then(response => response.json())
        .then(data => {
            hideLoading();  // 隱藏加載指示器
            if (data.success) {
                console.log('數據更新成功');
                updateSummaryCards(data);
                updateCurrencyTable(data.trade_info);
            } else {
                console.error('更新失敗:', data.error);
            }
        })
        .catch(error => {
            hideLoading();  // 隱藏加載指示器
            console.error('更新錯誤:', error);
            setTimeout(updateDashboard, 5000);  // 如果更新失敗，5秒後重試
        });
}

// 更新摘要卡片
function updateSummaryCards(data) {
    document.querySelector('.card:nth-child(1) p').textContent = data.total_investment.toFixed(2) + ' USDT';
    document.querySelector('.card:nth-child(2) p').textContent = data.usdt_balance.toFixed(2) + ' USDT';
    document.querySelector('.card:nth-child(3) p').textContent = data.daily_profit.toFixed(2) + ' USDT';
    document.querySelector('.card:nth-child(4) p').textContent = data.monthly_profit.toFixed(2) + ' USDT';
    document.querySelector('.card:nth-child(5) p').textContent = data.annual_return.toFixed(2) + '%';
    document.querySelector('.card:nth-child(6) p').textContent = data.total_profit.toFixed(2) + ' USDT';  // 新增總收益
}

function updateCurrencyTable(tradeInfo) {
    const tbody = document.querySelector('.currency-table tbody');
    tbody.innerHTML = '';  // 清空表格內容

    // 將貨幣按等待交易中和交易狀態排序
    const sortedCurrencies = Object.entries(tradeInfo).sort((a, b) => {
        // 等待交易中的貨幣優先
        if (a[1].waiting_for_open !== b[1].waiting_for_open) {
            return b[1].waiting_for_open - a[1].waiting_for_open;
        }
        // 正在交易的貨幣次之
        if (a[1].is_trading !== b[1].is_trading) {
            return b[1].is_trading - a[1].is_trading;
        }
        return 0;
    });

    // 渲染表格
    sortedCurrencies.forEach(([currency, info]) => {
        const row = document.createElement('tr');
        const totalAmount = info.positions ? info.positions.reduce((sum, position) => sum + (position.amount || 0), 0) : 0;

        row.innerHTML = `
            <td>${currency}/USDT</td>
            <td>${info.current_price ? info.current_price.toFixed(4) : '0.0000'}</td>
            <td>${totalAmount.toFixed(4)}</td>
            <td class="${info.total_profit > 0 ? 'profit' : 'loss'}">${info.total_profit.toFixed(2)}</td>
            <td>
                ${info.waiting_for_open ?
                    `<span class="status-waiting">等待交易中...</span>` :
                    (info.is_trading ?
                        `<a href="/manage_positions/${currency}" class="button-manage">管理持倉</a>` :
                        `<button onclick="startTrading('${currency}')" class="button-start">開始交易</button>`
                    )
                }
            </td>
        `;
        tbody.appendChild(row);
    });
}

// 開始交易
function startTrading(currency) {
    fetch(`/start_trading/${currency}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(data.message);  // 顯示包含布林通道下軌價格的訊息
            updateDashboard();    // 更新儀表板數據
        } else {
            alert(`開始交易失敗: ${data.error || '未知錯誤'}`);
        }
    })
    .catch(error => {
        console.error('開始交易失敗:', error);
        alert('開始交易失敗，請檢查網路連接');
    });
}

// 頁面載入時立即更新一次
document.addEventListener('DOMContentLoaded', function() {
    console.log('頁面載入完成，開始更新數據');
    updateDashboard();
});

// 每60秒更新一次數據
setInterval(updateDashboard, 60000);