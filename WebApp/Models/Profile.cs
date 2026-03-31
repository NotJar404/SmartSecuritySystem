using Microsoft.AspNetCore.Http;

namespace WebApp.Models
{
    public class Profile
    {
        public int Id { get; set; }

        // =========================
        // USER INFORMATION
        // =========================
        public string Name { get; set; }

        public string Username { get; set; }

        public string Email { get; set; } // read-only in view
        public string Role { get; set; }  // read-only in view

        // =========================
        // PROFILE IMAGE
        // =========================
        public string ProfileImagePath { get; set; } = "/images/default-profile.png"; // default image

        public IFormFile ProfileImage { get; set; } // for upload

        // =========================
        // CONSTRUCTOR
        // =========================
        public Profile()
        {
            // default constructor
        }

        public Profile(int id, string name, string username, string email, string role)
        {
            Id = id;
            Name = name;
            Username = username;
            Email = email;
            Role = role;
            ProfileImagePath = "/images/default-profile.png";
        }
    }
}