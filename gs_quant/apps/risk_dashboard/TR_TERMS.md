# Türkçe terimler

Arayüzdeki finans terimleri ve seçilme nedenleri. Bir terim değiştirilecekse `static/i18n.js` içinde değiştirilir; aşağıdaki
"Şimdiki" sütunundaki yazılar çevirilerle birebir eşleşmek zorundadır (bir test bunu denetler), bu yüzden bu dosya eskimez.
**Gözden geçirilmesi gerekenler** bölümü, bir finans uzmanının karar vermesi gereken yerleri gösterir.

| İngilizce | Şimdiki | Not |
|---|---|---|
| Value at risk | Riske maruz değer | Türkçe düzenleyici ve akademik metinlerde yaygın karşılık. Kısaltma VaR. |
| Maximum drawdown | Maksimum düşüş | Fon raporlarında yaygın kullanım. |
| Growth of 100 | 100 birimlik yatırımın değeri | Önceki "100’ün büyümesi" Türkçede doğal durmuyordu. |
| Christoffersen independence | Christoffersen bağımsızlık testi | Başlıkta "test" kelimesi eksikti, eklendi. |
| Annualized volatility | Yıllıklandırılmış volatilite | "Oynaklık" yerine volatilite: piyasa dilinde yaygın. |
| Sortino ratio | Sortino oranı | |
| Calmar ratio | Calmar oranı | |
| Omega ratio | Omega oranı | |
| Skewness | Çarpıklık | |
| Excess kurtosis (0 = normal) | Fazla basıklık (0 = normal) | "Aşırı basıklık" da kullanılır. |
| Downside deviation (annualized) | Aşağı yönlü sapma (yıllıklandırılmış) | |
| Tracking error | İzleme hatası | |
| Information ratio | Bilgi oranı | |
| Alpha | Alfa | |
| Diversification ratio | Çeşitlendirme oranı | |
| Basel traffic light | Basel trafik ışığı | Yeşil, sarı, kırmızı bölge. |
| Conditional coverage | Koşullu kapsama | |
| Rolling window (periods) | Kayan pencere (dönem) | |
| Horizon (periods) | Ufuk (dönem) | |
| Filtered VaR (EWMA) | Filtrelenmiş VaR (EWMA) | Üstel ağırlıklı hareketli ortalamayla süzülmüş tahmin. |

## Gözden geçirilmesi gerekenler

Bunlar benim seçimim ve tartışmaya açık. Karar verilirse yalnızca `static/i18n.js` değişir.

| İngilizce | Şimdiki | Seçenekler | Neden tartışmalı |
|---|---|---|---|
| Expected shortfall | Beklenen kayıp (ES) | Beklenen açık; koşullu riske maruz değer (CVaR) | "Beklenen kayıp" kredi riskinde başka bir kavramı (expected loss) da anlatır; karışabilir. |
| Breach | İhlal | Aşım; istisna | Basel geri testi metinlerinde "aşım" ya da "istisna sayısı" kullanıldığını biliyorum, ama hangisinin sizin çevrenizde yerleşik olduğunu bilmiyorum. |
