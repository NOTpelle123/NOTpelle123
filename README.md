- 👋 Hi, I’m @NOTpelle123
<!DOCTYPE html>
<html lang="sv">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grundläggande Webbsida</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f0f0f0;
            margin: 0;
            padding: 0;
        }

        header {
            background-color: #4CAF50;
            color: white;
            padding: 15px;
            text-align: center;
        }

        main {
            padding: 20px;
        }

        button {
            padding: 10px 20px;
            background-color: #4CAF50;
            color: white;
            border: none;
            cursor: pointer;
        }

        button:hover {
            background-color: #45a049;
        }

        footer {
            background-color: #333;
            color: white;
            text-align: center;
            padding: 10px 0;
            position: fixed;
            bottom: 0;
            width: 100%;
        }
    </style>
</head>
<body>
    <header>
        <h1>Välkommen till Min Webbsida</h1>
    </header>

    <main>
        <h2>Interaktiv JavaScript Funktion</h2>
        <p>Klicka på knappen för att se en hälsning:</p>
        <button onclick="visaHalsning()">Visa Hälsning</button>
        <p id="halsning"></p>
    </main>

    <footer>
        <p>Copyright © 2024 Min Webbsida</p>
    </footer>

    <script>
        function visaHalsning() {
            document.getElementById("halsning").innerHTML = "Hej och välkommen till min webbsida!";
        }
    </script>
</body>
</html>
