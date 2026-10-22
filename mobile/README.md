# 📱 CYD Mobile Monitor (Aplicativo de Controle Remoto para Smartphones)

Este diretório contém o aplicativo mobile do **CYD Hardware & Financial Market Monitor** para controle remoto sem fio da sua placa **ESP32-2432S028R (CYD - Cheap Yellow Display)** via Wi-Fi local.

---

## ⚡ 1. Método Recomendado: Uso Imediato sem Instalar Nada (Web PWA)

O Agente Desktop do CYD Monitor já possui um **servidor web de alta performance integrado**. Você não precisa compilar nenhum APK ou instalar SDKs no seu celular:

1. Abra o **CYD Hardware Monitor** no seu computador.
2. No painel principal, localize o card **📱 CONTROLE REMOTO PELO CELULAR (WI-FI)**.
3. Aponte a câmera do seu smartphone (Android ou iPhone) para o **QR Code** exibido na tela ou digite no navegador do celular o endereço local:
   ```
   http://<IP_DO_SEU_PC>:8088
   ```
   *(Exemplo: `http://192.168.0.109:8088`)*
4. **Pronto!** O aplicativo carrega instantaneamente no seu celular com:
   - 📺 Alternância instantânea entre as 7 telas (Telas 0 a 6).
   - 🎨 Estúdio de Cores RGB565 em tempo real (Paletas Matrix, Neon, Cyber, etc. e Sliders R/G/B).
   - 📊 Telemetria do PC ao vivo (CPU %, GPU %, RAM %, Disco, Rede).
   - 💰 Cotações da Bolsa e Cripto (Dólar, Euro, IBOVESPA, BTC, ETH, SOL) + Liga/Desliga Ticker.
   - 📸 **Upload direto da câmera ou galeria do celular** para o Cartão MicroSD da CYD!
   - ☀️ Controle de Brilho PWM do backlight da placa.
   - 📳 Feedback tátil / vibração nativa ao tocar nos botões.

*(Dica: No Safari do iOS toque em "Compartilhar > Adicionar à Tela de Início". No Chrome do Android toque nos três pontinhos e selecione "Instalar aplicativo" para usá-lo como um app nativo em tela cheia).*

---

## 🛠️ 2. Compilação do Aplicativo Nativo Flutter (Android APK / iOS)

Se você é desenvolvedor e deseja gerar um aplicativo nativo compilado:

### Pré-requisitos
- [Flutter SDK](https://flutter.dev/docs/get-started/install) instalado e configurado no PATH.
- Android Studio ou VS Code com extensão Flutter.

### Como rodar em modo de desenvolvimento
```bash
cd mobile
flutter pub get
flutter run
```

### Como gerar o APK de Release para Android
```bash
cd mobile
flutter build apk --release
```
O arquivo APK gerado estará em:
`mobile/build/app/outputs/flutter-apk/app-release.apk`

Transfira o APK para o seu celular Android e instale. Ao abrir o app, toque no botão superior direito para informar o IP do seu computador na rede local (ex: `http://192.168.0.109:8088`).
