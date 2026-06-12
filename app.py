from app import create_app

### starter appen

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)